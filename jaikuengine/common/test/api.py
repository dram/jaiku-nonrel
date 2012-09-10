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

from __future__ import with_statement
import datetime
import logging
import simplejson
from oauth import oauth
import mox

from django.conf import settings
from django.core import mail

from google.appengine.api import images

from common import api
from common import clean
from common import exception
from common import mail as common_mail
from common import models
from common import oauth_util
from common import profile
from common import util
from common import validate
from common.protocol import sms
from common.test import base
from common.test import util as test_util


class ApiIntegrationTest(base.FixturesTestCase):
  def setUp(self):
    super(ApiIntegrationTest, self).setUp()

    self.post_params = {"method": "post",
                        "nick": "popular@example.com",
                        "message": "message_1",
                        }


    self.url = "http://%s/api/json" % settings.DOMAIN
    self.old_utcnow = api.utcnow
    self.now = api.utcnow()


  def tearDown(self):
    api.utcnow = self.old_utcnow
    settings._target = None
    super(ApiIntegrationTest, self).tearDown()

  def get(self, url, parameters={}):
    response = self.client.get(url, parameters)
    try:
      rv = simplejson.loads(response.content)
      return rv
    except ValueError, e:
      print response.content
      raise

  def test_json_no_method(self):
    rv = self.get('/api/json')
    self.assertEqual(rv['status'], 'error')
    self.assertEqual(rv['code'], exception.NO_METHOD)

  def test_json_invalid_method(self):
    rv = self.get('/api/json', {"method": "INVALID_METHOD"})
    self.assertEqual(rv['status'], 'error')
    self.assertEqual(rv['code'], exception.INVALID_METHOD)

  def test_json_invalid_args(self):
    settings.API_DISABLE_VERIFICATION = True
    rv = self.get('/api/json', {"method": "actor_get"})
    self.assertEqual(rv['status'], 'error')
    self.assertEqual(rv['code'], exception.INVALID_ARGUMENTS)

  def test_json_invalid_oauth_request_no_oauth(self):
    settings.API_DISABLE_VERIFICATION = False
    rv = self.get('/api/json', {"method": "post"})
    self.assertEqual(rv['status'], 'error')
    # TODO(termie): update this when we have an error code, it is no longer
    #               an OAUTH_ERROR
    #self.assertEqual(rv['code'], exception.OAUTH_ERROR)

  def test_json_invalid_oauth_request_bad_tokens(self):
    settings.API_DISABLE_VERIFICATION = False
    settings.API_ALLOW_ROOT_PLAINTEXT = True

    sig_method = oauth_util.PLAINTEXT

    # test invalid consumer
    bad_consumer = oauth.OAuthConsumer('BAD_KEY', 'BAD_SECRET')
    request = oauth.OAuthRequest.from_consumer_and_token(
        bad_consumer,
        oauth_util.ROOT_TOKEN,
        http_url=self.url,
        parameters=self.post_params)
    request.sign_request(sig_method, bad_consumer, oauth_util.ROOT_TOKEN)

    rv = self.get('/api/json', request.parameters)

    self.assertEqual(rv['status'], 'error')
    self.assertEqual(rv['code'], exception.OAUTH_ERROR)

    # test invalid access token



    pass

  def test_json_hmacsha1_root_access(self):
    settings.API_DISABLE_VERIFICATION = False
    settings.API_ALLOW_ROOT_HMAC_SHA1 = False

    def _req():
      request = oauth.OAuthRequest.from_consumer_and_token(
          oauth_util.ROOT_CONSUMER,
          oauth_util.ROOT_TOKEN,
          http_url=self.url,
          parameters=self.post_params,
          )
      request.sign_request(oauth_util.HMAC_SHA1,
                           oauth_util.ROOT_CONSUMER,
                           oauth_util.ROOT_TOKEN
                           )

      rv = self.get('/api/json', request.parameters)
      return rv

    # fail
    rv = _req()
    self.assertEqual(rv['status'], 'error', "root hmac_sha1 should be disabled")
    self.assertEqual(rv['code'], exception.OAUTH_ERROR)

    # succeed
    settings.API_ALLOW_ROOT_HMAC_SHA1 = True
    rv = _req()
    self.assertEqual(rv['status'], 'ok', str(rv))

  def test_json_plaintext_root_access(self):
    settings.API_DISABLE_VERIFICATION = False
    settings.API_ALLOW_ROOT_PLAINTEXT = False

    def _req():
      request = oauth.OAuthRequest.from_consumer_and_token(
          oauth_util.ROOT_CONSUMER,
          oauth_util.ROOT_TOKEN,
          http_url=self.url,
          parameters=self.post_params,
          )
      request.sign_request(oauth_util.PLAINTEXT,
                           oauth_util.ROOT_CONSUMER,
                           oauth_util.ROOT_TOKEN
                           )

      rv = self.get('/api/json', request.parameters)
      return rv

    # fail
    rv = _req()
    self.assertEqual(rv['status'], 'error', "root plaintext should be disabled")
    self.assertEqual(rv['code'], exception.OAUTH_ERROR)

    # succeed
    settings.API_ALLOW_PLAINTEXT = True
    settings.API_ALLOW_ROOT_PLAINTEXT = True
    rv = _req()
    self.assertEqual(rv['status'], 'ok', str(rv))

  def test_json_params(self):
    settings.API_DISABLE_VERIFICATION = True

    params = { 'json_params': simplejson.dumps(self.post_params) }
    rv = self.get('/api/json', params)
    self.assertEqual(rv['status'], 'ok', str(rv))

  def test_presence_get_contacts(self):
    settings.API_DISABLE_VERIFICATION = True

    timestamp1 = datetime.datetime(2007, 01, 01, 02, 03, 04)
    timestamp2 = datetime.datetime(2008, 01, 01, 02, 03, 04)
    timestamp_between = datetime.datetime(2007, 06, 01, 02, 03, 04)
    api.utcnow = lambda: timestamp1
    rv = self.get('/api/json', {'method': 'presence_set',
                                'nick': 'root@example.com',
                                'status': 'bar'})
    api.utcnow = lambda: timestamp2
    rv = self.get('/api/json', {'method': 'presence_set',
                                'nick': 'celebrity@example.com',
                                'status': 'baz'})

    rv = self.get('/api/json', {'method': 'presence_get_contacts',
                                'nick': 'popular@example.com',
                                'since_time': str(timestamp_between)})
    self.assertEqual(rv.get('servertime', ''), str(timestamp2), str(rv))
    self.assertEqual(len(rv.get('rv', {}).get('contacts', [])), 2, str(rv))
    self.assertEqual(rv['rv']['contacts'][0]['presence'].get('extra', {}).get('status', ''),
                     'baz', str(rv))
    self.assertEqual(rv['rv']['contacts'][0]['presence'].get('extra', {}).get('given_name', ''),
                     'Cele', str(rv))
    self.assertEqual(rv['rv']['contacts'][0]['presence'].get('extra', {}).get('family_name', ''),
                     'Brity', str(rv))
    rv = self.get('/api/json', {'method': 'presence_get_contacts',
                                'nick': 'popular@example.com',
                                'since_time': str(timestamp2 +
                                                  datetime.timedelta(0, 1))})
    self.assertEqual(len(rv.get('rv', {}).get('contacts', [])), 1, str(rv))

class ApiUnitTest(base.FixturesTestCase):
  """a plethora of tests to make sure all the interfaces keep working """
  unpopular_nick = 'unpopular@example.com'
  popular_nick = 'popular@example.com'
  celebrity_nick = 'celebrity@example.com'
  hermit_nick = 'hermit@example.com'
  nonexist_nick = 'nonexist@example.com'
  annoying_nick = 'annoying@example.com'
  obligated_nick = 'obligated@example.com'
  root_nick = 'root@example.com'
  deleted_nick = 'deleted@example.com'
  popular_mobile = '+16505551212'
  celebrity_mobile = '+14085551212'
  nonexist_mobile = '+19495551212'

  public_entry_key = 'stream/popular@example.com/presence/12345'
  private_entry_key = 'stream/girlfriend@example.com/presence/16961'
  channel_entry_key = 'stream/#popular@example.com/presence/13345'
  deleted_entry_key = 'stream/popular@example.com/presence/12348'
  deleted_user_entry_key = 'stream/deleted@example.com/presence/10347'
  deleted_stream_entry_key = 'stream/popular@example.com/presence-deleted/17346'

  def setUp(self):
    super(ApiUnitTest, self).setUp()
    self.popular = api.actor_get(api.ROOT, self.popular_nick)
    self.hermit = api.actor_get(api.ROOT, self.hermit_nick)
    models.CachingModel.reset_cache()
    models.CachingModel.enable_cache(True)

  def tearDown(self):
    super(ApiUnitTest, self).tearDown()
    models.CachingModel.enable_cache(False)

  def assertPermissions(self, access_level, func, *args, **kw):
    for current_level in api.ACCESS_LEVELS:
      if '_read_only' in kw:
        del kw['_read_only']
      else:
        self._pre_setup()
      self.setUp()

      # stub out actor_owns_actor so that we don't get owner_required errors
      self.mox.stubs.Set(api, 'actor_owns_actor', lambda *args: True)

      should_fail = (api.ACCESS_LEVELS.index(access_level) > 
                     api.ACCESS_LEVELS.index(current_level))

      threw = False
      try:
        temp_actor = models.Actor(nick='temp', type='user')
        temp_actor.access_level = current_level
        new_args = (temp_actor,) + args
        func(*new_args, **kw)
        if should_fail:
          self.fail('Unexpected permission success, expected: %s, actual: %s'
                    % (access_level, current_level))
      except exception.ApiPermissionDenied, e:
        threw = True
        if not should_fail:
          self.fail('Unexpected permission fail, expected: %s, actual: %s'
                    % (access_level, current_level))
      except:
        # No 'finally' in 2.4
        self.tearDown()
        raise

      self.tearDown()

    self._pre_setup()
    self.setUp()
  
  # a bunch of basic permissions tests
  def assertAdminRequired(self, func, *args, **kw):
    self.assertPermissions(api.ADMIN_ACCESS, func, *args, **kw)
  
  def assertDeleteRequired(self, func, *args, **kw):
    self.assertPermissions(api.DELETE_ACCESS, func, *args, **kw)

  def assertWriteRequired(self, func, *args, **kw):
    self.assertPermissions(api.WRITE_ACCESS, func, *args, **kw)

  def assertReadRequired(self, func, *args, **kw):
    self.assertPermissions(api.READ_ACCESS, func, *args, **kw)

  def assertNoAccessRequired(self, func, *args, **kw):
    self.assertPermissions(api.NO_ACCESS, func, *args, **kw)

class AbuseUnitTest(ApiUnitTest):
  def test_perms(self):
    # basic perms
    self.assertAdminRequired(api.abuse_get_entry,
                             self.public_entry_key,
                             _read_only=True)
    self.assertWriteRequired(api.abuse_report_entry, 
                             self.popular_nick,
                             self.public_entry_key)

  def test_basic(self):
    api.abuse_report_entry(self.hermit, self.hermit_nick, self.public_entry_key)
    abuse_ref = api.abuse_get_entry(api.ROOT, self.public_entry_key)
    self.assertEquals(1, abuse_ref.count)

    api.abuse_report_entry(api.ROOT, 
                           api.ROOT.nick, 
                           self.public_entry_key)
    abuse_ref2 = api.abuse_get_entry(api.ROOT, self.public_entry_key)
    self.assertEquals(2, abuse_ref2.count)

    # don't count additional reports by the same user
    api.abuse_report_entry(self.hermit, self.hermit_nick, self.public_entry_key)
    abuse_ref3 = api.abuse_get_entry(api.ROOT, self.public_entry_key)
    self.assertEquals(2, abuse_ref3.count)

class ActivationUnitTest(ApiUnitTest):
  def test_activate_email(self):
    # perms
    self.assertRaises(exception.ApiOwnerRequired, 
                      api.activation_activate_email,
                      self.popular,
                      self.unpopular_nick,
                      'BAD CODE')

    # invalid code
    self.assertRaises(exception.ApiNotFound, 
                      api.activation_activate_email,
                      self.popular,
                      self.popular.nick,
                      'BAD CODE')

    # right code, wrong user
    self.assertRaises(exception.ApiNotFound, 
                      api.activation_activate_email,
                      self.popular,
                      self.popular.nick,
                      'TESTCODE')
    
    # right code, right user
    relation_ref = api.activation_activate_email(self.hermit, 
                                                 self.hermit.nick, 
                                                 'TESTCODE')
    self.assertEqual(self.hermit, 
                     api.actor_lookup_email(api.ROOT, self.hermit.nick))
    
    # code has been used up
    self.assertRaises(exception.ApiNotFound, 
                      api.activation_activate_email,
                      self.hermit,
                      self.hermit.nick,
                      'TESTCODE')
  
    self.mox.StubOutWithMock(api, 'activation_get_code')
    
    # email taken stub
    api.activation_get_code(
        self.popular, self.popular.nick, 'email', 'ANY CODE'
        ).AndReturn(models.Activation(actor=self.popular.nick,
                                      type='email',
                                      content=self.celebrity_nick))
    
    # email already yours stub
    api.activation_get_code(
        self.popular, self.popular.nick, 'email', 'ANY CODE'
        ).AndReturn(models.Activation(actor=self.popular.nick,
                                      type='email',
                                      content=self.popular_nick))
    self.mox.ReplayAll()

    # email taken
    self.assertRaises(exception.ApiAlreadyInUse, 
                      api.activation_activate_email,
                      self.popular,
                      self.popular.nick,
                      'ANY CODE')

    # email already yours, if you somehow got here fake success
    relation_ref = api.activation_activate_email(self.popular, 
                                                 self.popular.nick,
                                                 'ANY CODE')
    self.assertEquals(self.popular.nick, relation_ref.target)

  def test_activate_mobile(self):
    # perms
    self.assertRaises(exception.ApiOwnerRequired, 
                      api.activation_activate_mobile,
                      self.popular,
                      self.unpopular_nick,
                      'BAD CODE')

    # invalid code
    self.assertRaises(exception.ApiNotFound, 
                      api.activation_activate_mobile,
                      self.popular,
                      self.popular.nick,
                      'BAD CODE')

    # right code, wrong user
    self.assertRaises(exception.ApiNotFound, 
                      api.activation_activate_mobile,
                      self.popular,
                      self.popular.nick,
                      'TESTCODE')
    
    # right code, right user
    relation_ref = api.activation_activate_mobile(self.hermit, 
                                                  self.hermit.nick, 
                                                  'TESTCODE')
    mobile_number = '+14155551212'
    self.assertEqual(self.hermit, 
                     api.actor_lookup_mobile(api.ROOT, mobile_number))
    
    # code has been used up
    self.assertRaises(exception.ApiNotFound, 
                      api.activation_activate_mobile,
                      self.hermit,
                      self.hermit.nick,
                      'TESTCODE')
  
    self.mox.StubOutWithMock(api, 'activation_get_code')
    
    # mobile taken stub
    api.activation_get_code(
        self.popular, self.popular.nick, 'mobile', 'ANY CODE'
        ).AndReturn(models.Activation(actor=self.popular.nick,
                                      type='mobile',
                                      content='+14085551212'))
    
    # mobile already yours stub
    api.activation_get_code(
        self.popular, self.popular.nick, 'mobile', 'ANY CODE'
        ).AndReturn(models.Activation(actor=self.popular.nick,
                                      type='mobile',
                                      content='+16505551212'))
    self.mox.ReplayAll()

    # mobile taken
    self.assertRaises(exception.ApiAlreadyInUse, 
                      api.activation_activate_mobile,
                      self.popular,
                      self.popular.nick,
                      'ANY CODE')

    # mobile already yours, if you somehow got here fake success
    relation_ref = api.activation_activate_mobile(self.popular, 
                                                 self.popular.nick,
                                                 'ANY CODE')
    self.assertEquals('+16505551212', relation_ref.target)
    
  def test_create_and_get(self):
    self.assertPermissions(api.ADMIN_ACCESS, 
                           api.activation_create,
                           self.popular_nick,
                           'email',
                           self.popular_nick)

    self.assertPermissions(api.ADMIN_ACCESS, 
                           api.activation_get,
                           self.hermit_nick,
                           'email',
                           self.hermit_nick,
                           _read_only=True)

    activation_ref = api.activation_create(api.ROOT, 
                                           self.popular_nick,
                                           'email',
                                           self.popular_nick)
    
    other_ref = api.activation_get(api.ROOT, 
                                   self.popular_nick,
                                   'email',
                                   self.popular_nick)
  
    self.assertEqual(activation_ref, other_ref)
 
    # test that another create generates the same code
    second_ref = api.activation_create(api.ROOT, 
                                       self.popular_nick,
                                       'email',
                                       self.popular_nick)
    self.assertEqual(activation_ref.code, second_ref.code)

  def test_create_email(self):
    # fail with existing
    self.assertRaises(exception.ApiAlreadyInUse,
                      api.activation_create_email,
                      api.ROOT,
                      self.popular_nick,
                      self.popular_nick)
    

    self.mox.StubOutWithMock(validate, 'email')
    self.mox.StubOutWithMock(api, 'activation_create')
    
    # make sure we validate the email
    validate.email(self.hermit_nick)
    
    # make sure we call activation_create (so that all its checks are made)
    api.activation_create(
        api.ROOT, self.hermit_nick, 'email', self.hermit_nick
        ).AndReturn(models.Activation(actor=self.hermit_nick,
                                      type='email',
                                      content=self.hermit_nick))

    self.mox.ReplayAll()
    api.activation_create_email(
        api.ROOT, self.hermit_nick, self.hermit_nick)

  def test_create_mobile(self):
    # fail with existing
    self.assertRaises(exception.ApiAlreadyInUse,
                      api.activation_create_mobile,
                      api.ROOT,
                      self.popular_nick,
                      self.popular_mobile)
    

    self.mox.StubOutWithMock(clean, 'mobile')
    self.mox.StubOutWithMock(api, 'activation_create')
    
    # make sure we validate the mobile
    clean.mobile(self.nonexist_mobile).Once()
    
    # make sure we call activation_create (so that all its checks are made)
    api.activation_create(
        api.ROOT, self.hermit_nick, 'mobile', self.nonexist_mobile
        ).AndReturn(models.Activation(actor=self.hermit_nick,
                                      type='mobile',
                                      content=self.nonexist_mobile))

    self.mox.ReplayAll()
    api.activation_create_mobile(
        api.ROOT, self.hermit_nick, self.nonexist_mobile)

  def test_get_actor_email(self):
    activation_ref = api.activation_create_email(api.ROOT, 
                                                 self.popular_nick,
                                                 self.nonexist_nick)
    activations_ref = api.activation_get_actor_email(self.popular,
                                                     self.popular_nick)
    self.assertEquals(activations_ref[0], activation_ref)

  def test_get_actor_mobile(self):
    activation_ref = api.activation_create_mobile(api.ROOT, 
                                                  self.popular_nick,
                                                  self.nonexist_mobile)
    activations_ref = api.activation_get_actor_mobile(self.popular,
                                                      self.popular_nick)
    self.assertEquals(activations_ref[0], activation_ref)

  def test_get_by_email(self):
    self.assertPermissions(api.ADMIN_ACCESS,
                           api.activation_get_by_email,
                           self.hermit_nick,
                           _read_only=True)
    # find nothing for no email-ville
    self.assert_(not api.activation_get_by_email(api.ROOT, self.nonexist_nick))

    # find something for email-ville
    self.assert_(api.activation_get_by_email(api.ROOT, self.hermit_nick))

  def test_get_code(self):
    activation_ref = api.activation_create_email(api.ROOT,
                                                 self.popular_nick,
                                                 self.nonexist_nick)
    code_ref = api.activation_get_code(self.popular,
                                       self.popular_nick,
                                       activation_ref.type,
                                       activation_ref.code)
    self.assertEquals(code_ref, activation_ref)

  def test_get_email(self):
    activation_ref = api.activation_create_email(api.ROOT,
                                                 self.popular_nick,
                                                 self.nonexist_nick)
    email_ref = api.activation_get_email(api.ROOT,
                                         self.popular_nick,
                                         activation_ref.content)
    self.assertEquals(email_ref, activation_ref)

  def test_get_mobile(self):
    activation_ref = api.activation_create_mobile(api.ROOT,
                                                 self.popular_nick,
                                                 self.nonexist_mobile)
    mobile_ref = api.activation_get_mobile(api.ROOT,
                                           self.popular_nick,
                                           activation_ref.content)
    self.assertEquals(mobile_ref, activation_ref)
  
  def test_request_email(self):
    # this is a bit of an integration test and mostly replica of 
    # activation_create stuff
    
    # TODO(termie): figure out a good way to test throttling

    # fail with existing
    self.assertRaises(exception.ApiAlreadyInUse,
                      api.activation_request_email,
                      self.popular,
                      self.popular_nick,
                      self.popular_nick)

    # requesting multiple activations doesn't leave old ones
    for email in [self.nonexist_nick, '1' + self.nonexist_nick]:
      activation_ref = api.activation_request_email(self.popular,
                                                    self.popular_nick,
                                                    email)
      activations_ref = api.activation_get_actor_email(api.ROOT,
                                                       self.popular_nick)
      self.assertEqual(len(activations_ref), 1)
      self.assertEqual(activations_ref[0], activation_ref)
      self.clear_cache() # reset throttling

    self.mox.StubOutWithMock(api, 'activation_create_email')
    self.mox.StubOutWithMock(common_mail, 'email_confirmation_message')
    self.mox.StubOutWithMock(api, 'email_send')

    # make sure we call activation_create_email (so that its checks are made)
    api.activation_create_email(
        api.ROOT, self.hermit_nick, self.nonexist_nick
        ).AndReturn(models.Activation(actor=self.hermit_nick,
                                      type='email',
                                      content=self.nonexist_nick))
    
    common_mail.email_confirmation_message(self.hermit, mox.IgnoreArg()
        ).AndReturn(('subject', 'message', 'html_message'))
    
    api.email_send(api.ROOT,
                   self.nonexist_nick,
                   'subject',
                   'message',
                   html_message='html_message'
                   )

    self.mox.ReplayAll()

    api.activation_request_email(
        self.hermit, self.hermit_nick, self.nonexist_nick)

  def test_request_mobile(self):
    # this is a bit of an integration test and mostly replica of 
    # activation_create stuff
    
    # TODO(termie): figure out a good way to test throttling

    # fail with existing
    self.assertRaises(exception.ApiAlreadyInUse,
                      api.activation_request_mobile,
                      self.popular,
                      self.popular_nick,
                      self.popular_mobile)

    # requesting multiple activations doesn't leave old ones
    for mobile in [self.nonexist_mobile, self.nonexist_mobile + '1']:
      activation_ref = api.activation_request_mobile(self.popular,
                                                     self.popular_nick,
                                                     mobile)
      activations_ref = api.activation_get_actor_mobile(api.ROOT,
                                                       self.popular_nick)
      self.assertEqual(len(activations_ref), 1)
      self.assertEqual(activations_ref[0], activation_ref)
      self.clear_cache() # reset throttling

    self.mox.StubOutWithMock(api, 'activation_create_mobile')
    self.mox.StubOutWithMock(api, 'sms_send')

    # make sure we call activation_create_mobile (so that its checks are made)
    api.activation_create_mobile(
        api.ROOT, self.hermit_nick, self.nonexist_mobile
        ).AndReturn(models.Activation(actor=self.hermit_nick,
                                      type='mobile',
                                      code='SOMECODE',
                                      content=self.nonexist_mobile))
    
    
    api.sms_send(api.ROOT,
                    self.hermit_nick,
                    self.nonexist_mobile,
                    mox.IgnoreArg()
                    )

    self.mox.ReplayAll()

    api.activation_request_mobile(
        self.hermit, self.hermit_nick, self.nonexist_mobile)



class ApiUnitTestBasic(ApiUnitTest):
  def test_actor_get(self):
    # root public case
    root_public = api.actor_get(api.ROOT, self.popular_nick)
    self.assertEqual(root_public.nick, self.popular_nick)

    # root private case
    root_private = api.actor_get(api.ROOT, self.celebrity_nick)
    self.assertEqual(root_private.nick, self.celebrity_nick)

    # contact public case
    self.assertNoAccessRequired(api.actor_has_contact,
                                self.popular_nick,
                                self.celebrity_nick)
    contact_public = api.actor_get(self.popular, self.popular_nick)
    self.assertEqual(contact_public.nick, self.popular_nick)

    # contact private case
    contact_private = api.actor_get(self.popular, self.celebrity_nick)
    self.assertEqual(contact_private.nick, self.celebrity_nick)

    # test user public case
    test_public = api.actor_get(self.hermit, self.popular_nick)
    self.assertEqual(test_public.nick, self.popular_nick)

    # test perms
    self.assertNoAccessRequired(api.actor_get, self.popular_nick)

  def test_actor_get_actors(self):
    popular_nicks = [self.popular_nick, self.unpopular_nick]
    half_nicks = [self.popular_nick, self.celebrity_nick]
    celebrity_nicks = [self.celebrity_nick]

    # root public case
    root_public = api.actor_get_actors(api.ROOT, popular_nicks)
    self.assertEqual(len(root_public), 2)

    # root half case
    root_half = api.actor_get_actors(api.ROOT, half_nicks)
    self.assertEqual(len(root_half), 2)

    # root private case
    root_private = api.actor_get_actors(api.ROOT, celebrity_nicks)
    self.assertEqual(len(root_private), 1)


    # contact public case
    contact_public = api.actor_get_actors(self.popular, popular_nicks)
    self.assertEqual(len(contact_public), 2)

    # contact half case
    contact_half = api.actor_get_actors(self.popular, half_nicks)
    self.assertEqual(len(contact_half), 2)

    # contact private case
    contact_private = api.actor_get_actors(self.popular, celebrity_nicks)
    self.assertEqual(len(contact_private), 1)


    # test public case
    test_public = api.actor_get_actors(self.hermit, popular_nicks)
    self.assertEqual(len(test_public), 2)

    # test perms
    self.assertNoAccessRequired(api.actor_get_actors, [self.popular_nick])

  def test_actor_has_contact(self):
    # root public case
    root_public = api.actor_has_contact(api.ROOT, self.popular_nick,
                                        self.celebrity_nick) # YES
    self.assert_(root_public)

    root_private = api.actor_has_contact(api.ROOT, self.celebrity_nick,
                                        self.popular_nick) # YES
    self.assert_(root_private)

    root_notcontact = api.actor_has_contact(api.ROOT, self.popular_nick,
                                            self.unpopular_nick) # NO
    self.assert_(not root_notcontact)

    # test perms
    self.assertNoAccessRequired(api.actor_has_contact,
                                self.popular_nick,
                                self.celebrity_nick)

  def test_actor_add_contact(self):
    # Make sure it works between local users though
    actor_before = api.actor_get(api.ROOT, self.popular_nick)
    other_before = api.actor_get(api.ROOT, self.unpopular_nick)
    contacts_before = actor_before.extra['contact_count']
    followers_before = other_before.extra['follower_count']
    is_contact_before = api.actor_has_contact(api.ROOT, 
                                              self.popular_nick,
                                              self.unpopular_nick)
    self.assert_(not is_contact_before)

    api.actor_add_contact(api.ROOT, self.popular_nick, self.unpopular_nick)

    actor_after = api.actor_get(api.ROOT, self.popular_nick)
    other_after = api.actor_get(api.ROOT, self.unpopular_nick)
    contacts_after = actor_after.extra['contact_count']
    followers_after = other_after.extra['follower_count']
    is_contact_after = api.actor_has_contact(api.ROOT, 
                                             self.popular_nick,
                                             self.unpopular_nick)

    self.assertEqual(contacts_before + 1, contacts_after, "contacts count")
    self.assertEqual(followers_before + 1, followers_after, "followers count")
    self.assert_(is_contact_after)

    # Make sure we can repeat the whole process without nasty sideeffects
    actor_before = api.actor_get(api.ROOT, self.popular_nick)
    other_before = api.actor_get(api.ROOT, self.unpopular_nick)
    contacts_before = actor_before.extra['contact_count']
    followers_before = other_before.extra['follower_count']
    is_contact_before = api.actor_has_contact(api.ROOT, 
                                              self.popular_nick,
                                              self.unpopular_nick)
    self.assert_(is_contact_before)

    api.actor_add_contact(api.ROOT, self.popular_nick, self.unpopular_nick)

    actor_after = api.actor_get(api.ROOT, self.popular_nick)
    other_after = api.actor_get(api.ROOT, self.unpopular_nick)
    contacts_after = actor_after.extra['contact_count']
    followers_after = other_after.extra['follower_count']
    is_contact_after = api.actor_has_contact(api.ROOT, 
                                             self.popular_nick,
                                             self.unpopular_nick)

    self.assertEqual(contacts_before, contacts_after, "contacts count")
    self.assertEqual(followers_before, followers_after, "followers count")
    self.assert_(is_contact_after)


    # Make sure it requires write permissions
    self.assertWriteRequired(api.actor_add_contact,
                             self.popular_nick,
                             self.unpopular_nick)

    # Make sure we can't modify other people
    def _modify_other():
      api.actor_add_contact(self.hermit, self.popular_nick,
                            self.unpopular_nick)
    self.assertRaises(exception.ApiException, _modify_other)

    # TODO notification checks

  def test_actor_remove_contact(self):

    # must be a contact
    def _not_a_contact():
      api.actor_remove_contact(api.ROOT, self.popular_nick, self.unpopular_nick)

    self.assertRaises(exception.ApiException, _not_a_contact)

    # test perms
    self.assertDeleteRequired(api.actor_remove_contact,
                               self.unpopular_nick,
                               self.popular_nick)

  def test_actor_add_contact_subscriptions(self):
    # test that after we add a public user we are subscribed to
    # all their streams

    subscriber = api.actor_get(api.ROOT, self.popular_nick)
    subscriber_inbox = "inbox/%s/overview" % subscriber.nick

    public_target = api.actor_get(api.ROOT, self.unpopular_nick)

    public_streams = api.stream_get_actor(api.ROOT, self.unpopular_nick)
    self.assert_(len(public_streams))

    api.actor_add_contact(api.ROOT, subscriber.nick, public_target.nick)

    for stream in public_streams:
      self.assert_(api.subscription_is_active(api.ROOT,
                                              stream.key().name(),
                                              subscriber_inbox))


    # test that after we add a contacts only user we have created
    # pending subscriptions for all their streams
    private_target = api.actor_get(api.ROOT, self.hermit_nick)
    private_streams = api.stream_get_actor(api.ROOT, private_target.nick)
    self.assert_(len(private_streams))

    api.actor_add_contact(api.ROOT, subscriber.nick, private_target.nick)

    for stream in private_streams:
      self.assert_(api.subscription_exists(api.ROOT,
                                           stream.key().name(),
                                           subscriber_inbox))
      self.assert_(not api.subscription_is_active(api.ROOT,
                                                  stream.key().name(),
                                                  subscriber_inbox))



    # test that after a contacts-only user adds a user their subscriptions
    # that were marked as pending are allowed
    # XXX this test relies on the results of the previous test being correct
    subscriber_streams = api.stream_get_actor(api.ROOT, subscriber.nick)
    self.assert_(len(subscriber_streams))

    api.actor_add_contact(api.ROOT, private_target.nick, subscriber.nick)
    private_inbox = "inbox/%s/overview" % private_target.nick

    for stream in subscriber_streams:
      self.assert_(api.subscription_is_active(api.ROOT,
                                              stream.key().name(),
                                              private_inbox))

    for stream in private_streams:
      self.assert_(api.subscription_is_active(api.ROOT,
                                              stream.key().name(),
                                              subscriber_inbox))


    # test that after we remove a user we are unsubscribed
    # from all their feeds
    api.actor_remove_contact(api.ROOT, subscriber.nick, public_target.nick)

    for stream in public_streams:
      self.assert_(not api.subscription_exists(api.ROOT,
                                               stream.key().name(),
                                               subscriber_inbox))

    # test that after a private user removes a user they are
    # unsubscribed from all their feeds
    api.actor_remove_contact(api.ROOT, private_target.nick, subscriber.nick)

    for stream in subscriber_streams:
      self.assert_(not api.subscription_exists(api.ROOT,
                                               stream.key().name(),
                                               private_inbox))

    for stream in private_streams:
      self.assert_(not api.subscription_is_active(api.ROOT,
                                                  stream.key().name(),
                                                  subscriber_inbox))

      self.assert_(api.subscription_exists(api.ROOT,
                                           stream.key().name(),
                                           subscriber_inbox))

  def test_login_forgot_email(self):
    api.login_forgot(api.ROOT, self.celebrity_nick)
    self.assertEqual(len(mail.outbox), 1)
    self.assertEqual(mail.outbox[0].subject, 'Password reset')
    self.assertTrue(mail.outbox[0].body,
        'password has been reset.' > 0)

  def test_invite_request_email(self):
    api.invite_request_email(api.ROOT, self.celebrity_nick, 'foo@bar.com')
    self.assertEqual(len(mail.outbox), 1)
    self.assertEqual(mail.outbox[0].subject,
        'Cele Brity invited you to %s' % (settings.SITE_NAME))
    self.assertTrue(mail.outbox[0].body,
        'Cele Brity (celebrity) has invited you to join %s' % (settings.SITE_NAME))

class ApiUnitTestChannels(ApiUnitTest):
  def setUp(self):
    super(ApiUnitTestChannels, self).setUp()
    self.test_channel_nick = '#testchannel@example.com'
    api.channel_create(api.ROOT,
                       channel=self.test_channel_nick,
                       nick=self.popular_nick)

  def test_channel_get(self):
    channel_ref = api.channel_get(self.popular, self.test_channel_nick)
    self.assertEqual('#testchannel@example.com', channel_ref.nick)

  def test_channel_create_twice(self):
    def _create_channel_again():
        api.channel_create(api.ROOT,
                           channel=self.test_channel_nick,
                           nick=self.popular_nick)

    self.failUnlessRaises(exception.ApiException, _create_channel_again)

  def test_channel_has_member(self):
    self.assert_(api.channel_has_member(api.ROOT,
                                        self.test_channel_nick,
                                        self.popular_nick))
    self.failIf(api.channel_has_member(api.ROOT,
                                        self.test_channel_nick,
                                        self.unpopular_nick))

  def test_channel_join_twice(self):
    def _join_channel_again():
      api.channel_join(api.ROOT, self.popular_nick, self.test_channel_nick)

    self.failUnlessRaises(exception.ApiException, _join_channel_again)

  def test_channel_join_and_get_members(self):
    api.channel_join(api.ROOT, self.celebrity_nick, self.test_channel_nick)
    api.channel_join(api.ROOT, self.unpopular_nick, self.test_channel_nick)
    expected_members = [self.celebrity_nick,
                        self.popular_nick,
                        self.unpopular_nick]
    self.assertEquals(expected_members,
                      api.channel_get_members(api.ROOT, self.test_channel_nick))

  def test_channel_get_members_offset(self):
    api.channel_join(api.ROOT, self.celebrity_nick, self.test_channel_nick)
    api.channel_join(api.ROOT, self.unpopular_nick, self.test_channel_nick)
    expected_members = [self.popular_nick, self.unpopular_nick]
    self.assertEquals(expected_members,
                      api.channel_get_members(api.ROOT, self.test_channel_nick,
                                              offset=self.celebrity_nick))

  def test_channel_get_members_limit(self):
    api.channel_join(api.ROOT, self.celebrity_nick, self.test_channel_nick)
    api.channel_join(api.ROOT, self.unpopular_nick, self.test_channel_nick)
    self.assertEquals([self.celebrity_nick],
                      api.channel_get_members(api.ROOT, self.test_channel_nick,
                                              limit=1))

  def test_channel_create_increment_count(self):
    channel_ref = api.channel_get(self.popular, self.test_channel_nick)
    self.assertEquals(1, channel_ref.extra['member_count'])
    self.assertEquals(1, channel_ref.extra['admin_count'])
    popular_ref = api.actor_get(api.ROOT, self.popular_nick)
    self.assertEquals(2, popular_ref.extra['channel_count'])

  def test_channel_join_increment_count(self):
    hermit_ref = api.actor_get(api.ROOT, self.hermit_nick)
    self.assertEquals(0, hermit_ref.extra.get('channel_count', 0))
    api.channel_join(api.ROOT, self.hermit_nick, self.test_channel_nick)
    channel_ref = api.channel_get(api.ROOT, self.test_channel_nick)
    self.assertEquals(2, channel_ref.extra['member_count'])
    hermit_ref = api.actor_get(api.ROOT, self.hermit_nick)
    self.assertEquals(1, hermit_ref.extra['channel_count'])

  def test_channel_part_decrement_count(self):
    api.channel_join(api.ROOT, self.hermit_nick, self.test_channel_nick)
    api.channel_part(api.ROOT, self.hermit_nick, self.test_channel_nick)
    channel_ref = api.channel_get(api.ROOT, self.test_channel_nick)
    self.assertEquals(1, channel_ref.extra['member_count'])
    hermit_ref = api.actor_get(api.ROOT, self.hermit_nick)
    self.assertEquals(0, hermit_ref.extra['channel_count'])


class ApiUnitTestSubscriptions(ApiUnitTest):
  def test_subscription_request(self):
    topic = "stream/%s/presence"
    inbox = "inbox/%s/overview"

    # local to public local
    local_public = api.subscription_request(self.popular,
                                            topic % self.unpopular_nick,
                                            inbox % self.popular_nick)
    self.assertEqual(local_public.state, 'subscribed')

    # local to private local
    local_private = api.subscription_request(self.popular,
                                            topic % self.hermit_nick,
                                            inbox % self.popular_nick)
    self.assertEqual(local_private.state, 'pending')


    # local to nonexist local
    def _local_nonexist():
      local_public = api.subscription_request(self.popular,
                                              topic % self.nonexist_nick,
                                              inbox % self.popular_nick)
    self.assertRaises(exception.ApiException, _local_nonexist)

    # local to private already contact
    local_already = api.subscription_request(self.popular,
                                             topic % self.annoying_nick,
                                             inbox % self.popular_nick)
    self.assertEqual(local_already.state, 'subscribed')

    # can't add subscription with other user's target
    def _local_sneaky():
      local_sneaky = api.subscription_request(self.popular,
                                              topic % self.unpopular_nick,
                                              inbox % self.unpopular_nick)
    self.assertRaises(exception.ApiException, _local_sneaky)

  def test_post(self):
    public_actor = api.actor_get(api.ROOT, self.popular_nick)
    private_actor = api.actor_get(api.ROOT, self.hermit_nick)
    test_message = "test message"
    public_stream = 'stream/%s/presence' % public_actor.nick

    # minimal posting
    entry_ref = api.post(public_actor,
                         nick=public_actor.nick,
                         message=test_message)

    self.exhaust_queue_any()

    self.assert_(entry_ref)
    self.assert_(entry_ref.uuid)
    entry_ref_from_uuid = api.entry_get_uuid(public_actor, entry_ref.uuid)
    self.assert_(entry_ref_from_uuid)
    entry_key = entry_ref.key().name()
    entry_ref_from_key = api.entry_get(public_actor, entry_key)
    for check_ref in (entry_ref, entry_ref_from_uuid, entry_ref_from_key):
      self.assertEqual(check_ref.stream,
                       public_stream)
      self.assertEqual(check_ref.owner,
                       public_actor.nick)
      self.assertEqual(check_ref.actor,
                       public_actor.nick)

      self.assertEqual(entry_ref.stream, check_ref.stream)
      self.assertEqual(entry_ref.key(), check_ref.key())

    # prevent duplicates via uuid
    def _duplicate_uuid_same_actor():
      api.post(public_actor,
               nick=public_actor.nick,
               message=test_message,
               uuid=entry_ref.uuid)
    self.assertRaises(exception.ApiException, _duplicate_uuid_same_actor)
    def _duplicate_uuid_different_actor():
      api.post(private_actor,
               nick=private_actor.nick,
               message=test_message,
               uuid=entry_ref.uuid)
    self.assertRaises(exception.ApiException, _duplicate_uuid_different_actor)

    # prevent non-owner
    def _nonowner_nick():
      api.post(public_actor,
               nick=private_actor.nick,
               message=test_message,
               )
    self.assertRaises(exception.ApiException, _nonowner_nick)

    # prevent invalid nick
    def _invalid_nick(nick):
      api.post(public_actor,
               nick=nick,
               message=test_message,
               )
    for nick in ('!@#', ):
      self.assertRaises((exception.ApiException, exception.ValidationError),
                        _invalid_nick, nick)

    # prevent unknown nick
    def _unknown_nick():
      api.post(public_actor,
               nick=self.nonexist_nick,
               message=test_message,
               )
    self.assertRaises(exception.ApiException, _unknown_nick)

    # prevent invalid message
    def _invalid_message(msg):
      api.post(public_actor,
               nick=public_actor.nick,
               message=msg,
               )
    for msg in ('', '  '):
      self.assertRaises(exception.ApiException, _invalid_message, msg)

    # message is viewable to all active subscribers
    public_subscribers = api.subscription_get_topic(api.ROOT, public_stream)
    inbox_key = 'inboxentry/%s' % entry_key
    for sub in public_subscribers:
      sub_ref = api.actor_get(api.ROOT, sub.subscriber)
      overview_inbox = api.inbox_get_actor_overview(sub_ref, sub_ref.nick)
      self.assertEqual(overview_inbox[0], entry_key)


    # private posting creates a message
    private_stream = 'stream/%s/presence' % private_actor.nick
    other_public_actor_ref = api.actor_get(api.ROOT, 'unpopular@example.com')
    
    # create an active subscription
    api.actor_add_contact(public_actor, 
                          public_actor.nick, 
                          private_actor.nick
                          )
    api.actor_add_contact(private_actor,
                          private_actor.nick,
                          public_actor.nick,
                          )
    # and an inactive one
    api.actor_add_contact(other_public_actor_ref, 
                          other_public_actor_ref.nick,
                          private_actor.nick)

    # minimal posting
    entry_ref = api.post(private_actor,
                         nick=private_actor.nick,
                         message=test_message)

    self.exhaust_queue_any()

    self.assert_(entry_ref)
    self.assert_(entry_ref.uuid)
    
    entry_key = entry_ref.key().name()

    def _private_entry_from_uuid():
      entry_ref_from_uuid = api.entry_get_uuid(other_public_actor_ref, 
                                               entry_ref.uuid)
    self.assertRaises(exception.ApiException, _private_entry_from_uuid)
    
    def _private_entry_from_key():
      entry_ref_from_key = api.entry_get(other_public_actor_ref, entry_key)
    self.assertRaises(exception.ApiException, _private_entry_from_key)

    entry_ref_from_uuid = api.entry_get_uuid(public_actor, entry_ref.uuid)
    entry_ref_from_key = api.entry_get(public_actor, entry_key)
    entry_ref_from_uuid_self = api.entry_get_uuid(private_actor, entry_ref.uuid)
    entry_ref_from_key_self = api.entry_get(private_actor, entry_key)

    for check_ref in (entry_ref, 
                      entry_ref_from_uuid, 
                      entry_ref_from_key,
                      entry_ref_from_uuid_self,
                      entry_ref_from_key_self):
      self.assertEqual(check_ref.stream,
                       private_stream)
      self.assertEqual(check_ref.owner,
                       private_actor.nick)
      self.assertEqual(check_ref.actor,
                       private_actor.nick)

      self.assertEqual(entry_ref.stream, check_ref.stream)
      self.assertEqual(entry_ref.key(), check_ref.key())


    # message is not viewable to all inactive subscribers
    private_subscribers = api.subscription_get_topic(api.ROOT, private_stream)
    inbox_key = 'inboxentry/%s' % entry_key
    self.assert_(private_subscribers)
    for sub in private_subscribers:
      sub_ref = api.actor_get(api.ROOT, sub.subscriber)
      overview_inbox = api.inbox_get_actor_overview(sub_ref, sub_ref.nick)
      if sub.state == 'pending':
        self.assertNotEqual(overview_inbox[0], entry_key)
      elif sub.state == 'subscribed':
        self.assertEqual(overview_inbox[0], entry_key)

    # thumbnail_url
    entry_ref = api.post(public_actor,
                         nick=public_actor.nick,
                         message=test_message,
                         thumbnail_url='http://flickr.com/')
    self.assertEqual(entry_ref.extra['thumbnail_url'], 'http://flickr.com/')
    pass

  def test_post_channel(self):
    # test that using the hash (#) notation posts to a channel
    pass

  def test_post_reply(self):
    # test that using the at (@) notation attempts to reply
    pass

  def test_comment(self):
    """ test that commentors are subscribed to further comments on posts
    they have commented on
    """
    popular_ref = api.actor_get(api.ROOT, 'popular')
    celebrity_ref = api.actor_get(api.ROOT, 'celebrity')
    unpopular_ref = api.actor_get(api.ROOT, 'unpopular')
    hermit_ref = api.actor_get(api.ROOT, 'hermit')
    
    # an entry with no comments
    entry_ref = api.entry_get(
        api.ROOT, 'stream/popular@example.com/presence/12346')

    # first comment, unpopular should not see it
    comment_first_ref = api.entry_add_comment(
        hermit_ref,
        stream=entry_ref.stream,
        entry=entry_ref.keyname(),
        nick=hermit_ref.nick,
        content='hermit comment')
    
    self.exhaust_queue_any()

    unpopular_inbox = api.inbox_get_actor_overview(unpopular_ref, unpopular_ref.nick)
    self.assertNotEqual(unpopular_inbox[0], comment_first_ref.keyname())
  
    # unpopular comments, a subscription should be created
    comment_second_ref = api.entry_add_comment(
        unpopular_ref,
        stream=entry_ref.stream,
        entry=entry_ref.keyname(),
        nick=unpopular_ref.nick,
        content='unpopular comment')

    self.exhaust_queue_any()

    unpopular_inbox = api.inbox_get_actor_overview(unpopular_ref, unpopular_ref.nick)
    self.assertEqual(unpopular_inbox[0], comment_second_ref.keyname())
    
    # hermit comments again, unpopular should see this one
    comment_third_ref = api.entry_add_comment(
        hermit_ref,
        stream=entry_ref.stream,
        entry=entry_ref.keyname(),
        nick=hermit_ref.nick,
        content='hermit comment 2')

    self.exhaust_queue_any()

    unpopular_inbox = api.inbox_get_actor_overview(unpopular_ref, unpopular_ref.nick)
    self.assertEqual(unpopular_inbox[0], comment_third_ref.keyname())
    # Should see them via the post
    comments = api.entry_get_comments(unpopular_ref, entry_ref.keyname())
    self.assertEqual(3, len(comments))
    comments = api.entry_get_comments(popular_ref, entry_ref.keyname())
    self.assertEqual(3, len(comments))
    comments = api.entry_get_comments(celebrity_ref, entry_ref.keyname())
    self.assertEqual(3, len(comments))

    # test commenting via entry's uuid, unpopular should see
    comment_fourth_ref = api.entry_add_comment_with_entry_uuid(
        unpopular_ref,
        entry_uuid=entry_ref.uuid,
        nick=unpopular_ref.nick,
        content='unpopular comment 3')

    self.exhaust_queue_any()

    unpopular_inbox = api.inbox_get_actor_overview(unpopular_ref, unpopular_ref.nick)
    self.assertEqual(unpopular_inbox[0], comment_fourth_ref.keyname())

  def test_keyvalue(self):
    key = 'key1'
    value = 'value1'
    put_keyvalue = api.keyvalue_put(api.ROOT, self.popular_nick,
                                    key, value)
    got_keyvalue = api.keyvalue_get(api.ROOT, self.popular_nick,
                                    key);
    for keyvalue in (put_keyvalue, got_keyvalue):
      self.assertEquals(keyvalue.keyname, key)
      self.assertEquals(keyvalue.value, value)

    got_keyvalue = api.keyvalue_get(api.ROOT, self.popular_nick,
                                    'nosuchkey');
    self.assertEquals(got_keyvalue, None)

    def _write_somebody_elses():
      put_keyvalue = api.keyvalue_put(self.popular, self.unpopular_nick,
                                      key, value)
    self.assertRaises(exception.ApiException, _write_somebody_elses)
    def _read_somebody_elses():
      got_keyvalue = api.keyvalue_get(self.popular, self.unpopular_nick,
                                      key)
    self.assertRaises(exception.ApiException, _read_somebody_elses)
    put_keyvalue = api.keyvalue_put(api.ROOT, self.popular_nick,
                                    'p1', value)
    put_keyvalue = api.keyvalue_put(api.ROOT, self.popular_nick,
                                    'p2', value)
    put_keyvalue = api.keyvalue_put(api.ROOT, self.unpopular_nick,
                                    'p2', value)
    put_keyvalue = api.keyvalue_put(api.ROOT, self.popular_nick,
                                    'r', value)

    values = api.keyvalue_prefix_list(api.ROOT, self.popular_nick, 'p')
    self.assertEquals(len(values), 2)
    values = api.keyvalue_prefix_list(api.ROOT, self.popular_nick, 'p1')
    self.assertEquals(len(values), 1)
    values = api.keyvalue_prefix_list(api.ROOT, self.popular_nick, 'r')
    self.assertEquals(len(values), 1)
    values = api.keyvalue_prefix_list(api.ROOT, self.popular_nick, 'x')
    self.assertEquals(len(values), 0)
    values = api.keyvalue_prefix_list(api.ROOT, self.unpopular_nick, 'p')
    self.assertEquals(len(values), 1)

  def test_stream_get_streams(self):
    public_streams = ['stream/popular@example.com/presence',
                      'stream/unpopular@example.com/presence']
    private_streams = ['stream/hermit@example.com/presence']
    nonexist_streams = ['stream/nonexist@example.com/presence']
    all_streams = public_streams + private_streams + nonexist_streams

    # basic test
    streams = api.stream_get_streams(self.popular, public_streams)
    for x in public_streams:
      self.assert_(streams[x])

    # filter private
    streams = api.stream_get_streams(self.popular, all_streams)
    for x in public_streams:
      self.assert_(streams[x])
    for x in (private_streams + nonexist_streams):
      self.assert_(not streams.get(x, None))

class ApiUnitTestRemove(ApiUnitTest):
  def setUp(self):
    super(ApiUnitTestRemove, self).setUp()
    self.public_actor = api.actor_get(api.ROOT, self.popular_nick)

  def _post(self, actor):
    test_message = "test message"
    entry_ref = api.post(actor,
                         nick = actor.nick,
                         message = test_message)
    self.exhaust_queue_any()
    keyname = entry_ref.key().name()
    got_entry = api.entry_get(actor, keyname)
    self.assertTrue(got_entry)
    return got_entry

  def _comment(self, actor, entry):
    test_comment = "test comment"
    comment = api.entry_add_comment(
        actor,
        nick = actor.nick,
        content = test_comment,
        entry = entry.key().name(),
        stream = entry.stream)

    self.exhaust_queue_any()

    keyname = comment.key().name()
    got_entry = api.entry_get(actor, keyname)
    self.assertTrue(got_entry)
    comments = api.entry_get_comments(actor, entry.key().name())
    self.assertEqual(len(comments), 1)
    entry_and_comments = api.entry_get_comments_with_entry_uuid(actor,
                                                                entry.uuid)
    self.assertEqual(len(entry_and_comments), 1)
    self.assertEqual(entry_and_comments.to_api()['entry']['uuid'], entry.uuid)
    return got_entry

  def _test_in_overview(self, stream, keyname, should_exist):
    public_subscribers = api.subscription_get_topic(api.ROOT, stream)
    self.assertTrue(len(public_subscribers) > 0)
    for sub in public_subscribers:
      sub_ref = api.actor_get(api.ROOT, sub.subscriber)

      # getting the list of overview entries doesn't yet filter out
      # deleted items
      overview_inbox = api.inbox_get_actor_overview(sub_ref, sub_ref.nick)
      overview_inbox = api.entry_get_entries_dict(sub_ref, overview_inbox)
      if should_exist:
        self.assertTrue(keyname in overview_inbox)
      else:
        self.assertFalse(keyname in overview_inbox)

  def test_remove_post(self):
    entry_ref = self._post(self.public_actor)
    keyname = entry_ref.key().name()
    stream = entry_ref.stream
    self._test_in_overview(stream, keyname, True)

    api.entry_remove(self.public_actor, keyname)
    no_entry = api.entry_get_safe(self.public_actor, keyname)
    self.assertFalse(no_entry)
    self._test_in_overview(stream, keyname, False)

  def test_remove_comment(self):
    entry = self._post(self.public_actor)
    comment = self._comment(self.public_actor, entry)
    stream = comment.stream
    keyname = comment.key().name()
    self._test_in_overview(stream, keyname, True)
 
    entry_ref_pre = api.entry_get(api.ROOT, entry.key().name())
    self.assertEqual(entry_ref_pre.extra['comment_count'], 1)

    api.entry_remove_comment(self.public_actor, keyname)
    no_entry = api.entry_get_safe(self.public_actor, keyname)
    self.assertFalse(no_entry)
    self._test_in_overview(stream, keyname, False)
    comments = [c for c in api.entry_get_comments(self.public_actor,
                                                  entry.key().name()) if c]
    self.assertEqual(len(comments), 0)

    entry_ref_post = api.entry_get(api.ROOT, entry.key().name())
    self.assertEqual(entry_ref_post.extra['comment_count'], 0)

  def test_remove_post_with_comment(self):
    entry = self._post(self.public_actor)
    comment = self._comment(self.public_actor, entry)
    stream = comment.stream
    comment_keyname = comment.key().name()
    self._test_in_overview(stream, comment_keyname, True)

    api.entry_remove(self.public_actor, entry.key().name())
    no_entry = api.entry_get_safe(self.public_actor, comment_keyname)
    self.assertFalse(no_entry)
    self._test_in_overview(stream, comment_keyname, False)
    
    self.assertRaises(exception.ApiException, api.entry_get_comments, self.public_actor, entry.key().name())

class ApiUnitTestPrivacy(ApiUnitTest):
  def test_change_public_to_private(self):
    public_actor = api.actor_get(api.ROOT, self.popular_nick)
    test_message = "test message"
    public_stream = 'stream/%s/presence' % public_actor.nick
    entry_ref = api.post(public_actor,
                         nick=public_actor.nick,
                         message=test_message)
    self.exhaust_queue_any()
    public_subscribers = api.subscription_get_topic(api.ROOT, public_stream)
    self.assertTrue(public_subscribers)

    for sub in public_subscribers:
      sub_ref = api.actor_get(api.ROOT, sub.subscriber)
      overview_inbox = api.inbox_get_actor_overview(sub_ref, sub_ref.nick)
      self.assertEqual(overview_inbox[0], entry_ref.keyname())

    api.settings_change_privacy(public_actor, public_actor.nick,
                                api.PRIVACY_CONTACTS)
    for sub in public_subscribers:
      sub_ref = api.actor_get(api.ROOT, sub.subscriber)
      overview_inbox = api.inbox_get_actor_overview(sub_ref, sub_ref.nick)
      overview_entries = api.entry_get_entries(sub_ref, overview_inbox)

      if (api.actor_has_contact(api.ROOT, public_actor.nick, sub_ref.nick) or
          public_actor.nick == sub_ref.nick):
        self.assertEqual(overview_entries[0].keyname(), entry_ref.keyname())
      else:
        if not overview_entries:
          pass
        else:
          self.assertNotEqual(overview_entries[0].keyname(),
                              entry_ref.keyname(),
                              "non-contact %s sees entry %s" % (
                                  sub_ref.nick, entry_ref.keyname()))

class ApiUnitTestPresence(ApiUnitTest):
  def setUp(self):
    super(ApiUnitTestPresence, self).setUp()
    self.public_actor = api.actor_get(api.ROOT, self.popular_nick)
    self.old_utcnow = api.utcnow
    self.now = api.utcnow()
    api.utcnow = lambda: self.now

  def tearDown(self):
    api.utcnow = self.old_utcnow

  def _set(self, actor, nick, timestamp, status):
    if timestamp:
      self.now = timestamp
    else:
      utcnow = self.old_utcnow
      self.now = utcnow()
    presence = api.presence_set(
        actor, nick = nick, senders_timestamp = timestamp, status = status)
    self.assertTrue(presence)
    if timestamp:
      self.assertEqual(presence.updated_at, timestamp)
      self.assertEqual(presence.extra['senders_timestamp'], timestamp)
    return presence

  def test_set_and_get(self):
    timestamp = datetime.datetime.utcnow()
    presence = self._set(self.public_actor, self.public_actor.nick,
                         timestamp, 'pl1')
    got_presence = api.presence_get(self.public_actor, self.public_actor.nick)
    self.assertTrue(got_presence)
    self.assertEqual(got_presence.updated_at, timestamp)
    self.assertEqual(got_presence, presence)
    api.presence_set(self.public_actor, self.public_actor.nick,
                     location = 'loc1')
    # test previous fields are kept unless overridden
    got_presence = api.presence_get(self.public_actor, self.public_actor.nick)
    self.assertEqual(got_presence.extra['status'], 'pl1')
    self.assertEqual(got_presence.extra['location'], 'loc1')

  def test_history(self):
    timestamp1 = datetime.datetime(2007, 01, 01, 02, 03, 04, 5)
    timestamp2 = datetime.datetime(2008, 01, 01, 02, 03, 04, 5)
    timestamp_between = datetime.datetime(2007, 06, 01, 02, 03, 04, 5)
    timestamp_before = datetime.datetime(2006, 01, 01, 02, 03, 04, 5)
    timestamp_after = datetime.datetime(2009, 01, 01, 02, 03, 04, 5)

    self._set(self.public_actor, self.public_actor.nick, timestamp1, 'bar')
    self._set(self.public_actor, self.public_actor.nick, timestamp2, 'baz')
    presence = api.presence_get(
        self.public_actor, self.public_actor.nick)
    presence1 = api.presence_get(
        self.public_actor, self.public_actor.nick, at_time = timestamp1)
    presence2 = api.presence_get(
        self.public_actor, self.public_actor.nick, at_time = timestamp2)
    presence_between = api.presence_get(
        self.public_actor, self.public_actor.nick, at_time = timestamp_between)
    self.assertEquals(presence1.extra['status'], 'bar')
    self.assertEquals(presence, presence2)
    self.assertEquals(presence2.extra['status'], 'baz')
    self.assertEquals(presence_between, presence1)

    presence_before = api.presence_get(
        self.public_actor, self.public_actor.nick, at_time = timestamp_before)
    self.assertEquals(presence_before, None)
    presence_after = api.presence_get(
        self.public_actor, self.public_actor.nick, at_time = timestamp_after)
    self.assertEquals(presence_after, presence2)

  def test_permissions(self):
    private_actor = api.actor_get(api.ROOT, self.celebrity_nick)
    unpopular_actor = api.actor_get(api.ROOT, self.unpopular_nick)
    hermit_actor = api.actor_get(api.ROOT, self.hermit_nick)

    def _set_by_other():
      self._set(self.public_actor, private_actor.nick, None, '')
    self.assertRaises(exception.ApiException, _set_by_other)

    self._set(private_actor, private_actor.nick, None, '')
    def _get_private_by_noncontact():
      api.presence_get(unpopular_actor, private_actor.nick)
    self.assertRaises(exception.ApiException, _get_private_by_noncontact)

    # Get private by contact
    api.presence_get(self.public_actor, private_actor.nick)

    # Get public by non-contact
    self._set(self.public_actor, self.public_actor.nick, None, '')
    api.presence_get(hermit_actor, self.public_actor.nick)

  def test_contacts(self):
    publics_contact_1 = api.actor_get(api.ROOT, self.celebrity_nick)
    publics_contact_2 = api.actor_get(api.ROOT, self.root_nick)
    timestamp1 = datetime.datetime(2007, 01, 01, 02, 03, 04, 5)
    timestamp2 = datetime.datetime(2008, 01, 01, 02, 03, 04, 5)
    timestamp_before = datetime.datetime(2006, 01, 01, 02, 03, 04, 5)
    timestamp_between = datetime.datetime(2007, 06, 01, 02, 03, 04, 5)
    timestamp_after = datetime.datetime(2009, 01, 01, 02, 03, 04, 5)
    self._set(publics_contact_1, publics_contact_1.nick, timestamp1, 'bar')
    self._set(publics_contact_2, publics_contact_2.nick, timestamp2, 'baz')
    # Get current (set + autogenerated at 2008)
    presences = api.presence_get_contacts(self.public_actor,
                                          self.public_actor.nick)
    self.assertEquals(len(presences), 3)
    # Get all by timestamp (set + autogenerated at 2008)
    presences = api.presence_get_contacts(self.public_actor,
                                          self.public_actor.nick,
                                          timestamp_before)
    self.assertEquals(len(presences), 3)
    # Get one by timestamp (set + autogenerated at 2008)
    presences = api.presence_get_contacts(self.public_actor,
                                          self.public_actor.nick,
                                          timestamp_between)
    self.assertEquals(len(presences), 2)
    # Get none by timestamp
    presences = api.presence_get_contacts(self.public_actor,
                                          self.public_actor.nick,
                                          timestamp_after)
    self.assertEquals(len(presences), 0)

class ApiUnitTestActivation(ApiUnitTest):
  def test_activation_request_email(self):
    actor = api.actor_get(api.ROOT, self.celebrity_nick)
    self.assertTrue(actor)
    activation_ref = api.activation_request_email(actor, actor.nick, settings.DEFAULT_UNITTEST_TO_EMAIL)
    self.assertTrue(activation_ref)
    self.assertEqual(len(mail.outbox), 1)
    self.assertEqual(mail.outbox[0].subject, 'Welcome! Confirm your email')
    self.assertTrue(mail.outbox[0].body, 'Thanks for joining' > 0)

  def test_activation_clear_old_email(self):
    settings.EMAIL_LIMIT_DOMAIN = None

    actor = api.actor_get(api.ROOT, self.celebrity_nick)
    activation_ref = api.activation_request_email(
        actor, actor.nick, 'example@example.com')
    activations = api.activation_get_actor_email(api.ROOT, actor.nick)
    self.assertEqual(len(activations), 1)

    activation_ref = api.activation_request_email(
        actor, actor.nick, 'example2@example.com')
    activations = api.activation_get_actor_email(api.ROOT, actor.nick)
    self.assertEqual(len(activations), 1)

  def test_activation_request_mobile(self):
    actor = api.actor_get(api.ROOT, self.celebrity_nick)

    activation_ref = api.activation_request_mobile(
        actor, actor.nick, '+19495551212')
    self.assertEqual(len(sms.outbox), 1)

    activations = api.activation_get_actor_mobile(api.ROOT, actor.nick)
    self.assertEqual(len(activations), 1)

    activation_ref = api.activation_request_mobile(
        actor, actor.nick, '+19195551212')
    activations = api.activation_get_actor_mobile(api.ROOT, actor.nick)
    self.assertEqual(len(activations), 1)
    
  def test_activation_activate_mobile(self):
    actor_ref = api.actor_get(api.ROOT, self.celebrity_nick)
    mobile = '+19495551212'
    activation_ref = api.activation_request_mobile(
        actor_ref, actor_ref.nick, mobile)
    
    rel_ref = api.activation_activate_mobile(
        actor_ref, actor_ref.nick, activation_ref.code)
    
    lookup_ref = api.actor_lookup_mobile(actor_ref, mobile)

    self.assertEqual(lookup_ref.nick, actor_ref.nick)

    def _checkRepeat():
      rel_ref = api.activation_activate_mobile(
          actor_ref, actor_ref.nick, activation_ref.code)
    self.assertRaises(exception.ApiException, _checkRepeat)

    def _checkDuplicate():
      activation_ref = api.activation_request_mobile(
          actor_ref, actor_ref.nick, mobile)
    self.assertRaises(exception.ApiException, _checkDuplicate)

  def test_login_reset_delete_activation_afterwards(self):
    actor_ref = api.actor_get(api.ROOT, self.celebrity_nick)
    api.login_forgot(actor_ref, actor_ref.nick)
    email = api.email_get_actor(api.ROOT, actor_ref.nick)
    activation_ref = api.activation_get(api.ROOT, actor_ref.nick, 
                                        'password_lost', email)
    hash = util.hash_generic(activation_ref.code)
    api.login_reset(actor_ref, email, hash)
    self.assertRaises(exception.ApiException,
                      lambda: api.login_reset(actor_ref, email, hash))


class ApiUnitTestPost(ApiUnitTest):
  def test_post_simple(self):
    popular_ref = api.actor_get(api.ROOT, self.popular_nick)
    test_message = "test_message"

    l = profile.label('api_simple_post')
    entry_ref = api.post(popular_ref, 
                         nick=popular_ref.nick,
                         message=test_message)
    l.stop()
    self.assertEqual(entry_ref.stream, 'stream/popular@example.com/presence')

  def test_post_channel(self):
    l = profile.label('api_actor_get_as_root')
    popular_ref = api.actor_get(api.ROOT, self.popular_nick)
    l.stop()
    test_messages = [('#popular', 'test_message'),
                     ('#popular@example.com', 'test message 2'),
                     ('#popular:', 'test message')
                     ]

    for target, message in test_messages:
      test_message = '%s %s' % (target, message)
      l = profile.label('api_post_channel')
      entry_ref = api.post(popular_ref, 
                           nick=popular_ref.nick,
                           message=test_message)
      l.stop()
      self.assertEqual(entry_ref.stream, 'stream/#popular@example.com/presence')
      self.assertEqual(entry_ref.extra['title'], message)

  def test_post_too_long(self):
    popular_ref = api.actor_get(api.ROOT, self.popular_nick)
    test_message = "a" * 200;
    expected = test_message[:140]
    entry_ref = api.post(popular_ref,
                         nick=popular_ref.nick,
                         message=test_message)
    self.assertEqual(entry_ref.stream, 'stream/popular@example.com/presence')
    self.assertEqual(entry_ref.extra['title'], expected)

  def test_location_in_post(self):
    popular_ref = api.actor_get(api.ROOT, self.popular_nick)
    entry_ref = api.post(popular_ref,
                         nick=popular_ref.nick,
                         message='testing 123')
    self.failIf(entry_ref.extra['location'], 
                'did not expect non-empty location in %s' % (entry_ref.extra))
    api.presence_set(popular_ref, nick=popular_ref.nick, location='mtv')
    entry_ref = api.post(popular_ref,
                         nick=popular_ref.nick,
                         message='testing 123')
    self.assertEqual(entry_ref.extra['location'], 'mtv')
    api.presence_set(popular_ref, nick=popular_ref.nick, location='sfo')
    entry_ref = api.post(popular_ref,
                         nick=popular_ref.nick,
                         message='testing 123')
    self.assertEqual(entry_ref.extra['location'], 'sfo')
    entry_ref = api.post(popular_ref,
                         nick=popular_ref.nick,
                         message='testing 123',
                         location='oak')
    self.assertEqual(entry_ref.extra['location'], 'oak')


class ApiUnitTestSpam(ApiUnitTest):

  def setUp(self):
    super(ApiUnitTestSpam, self).setUp()
    self.popular_ref = api.actor_get(api.ROOT, self.popular_nick)
    self.unpopular_ref = api.actor_get(api.ROOT, self.unpopular_nick)
    self.celebrity_ref = api.actor_get(api.ROOT, self.celebrity_nick)
    self.entry_ref = api.post(self.popular_ref,
                              nick=self.popular_nick,
                              message='foo')

  def test_entry_mark_as_spam_single_user(self):
    abuse_ref = api.entry_mark_as_spam(self.unpopular_ref,
                                       self.entry_ref.keyname())
    self.assertEqual(abuse_ref.entry, self.entry_ref.keyname())
    self.assertEqual(abuse_ref.actor, self.popular_nick)
    self.assertEqual(abuse_ref.reports, [self.unpopular_nick])
    self.assertEqual(abuse_ref.count, 1)

  def test_entry_mark_as_spam_single_user_multiple_times(self):
    api.entry_mark_as_spam(self.unpopular_ref, self.entry_ref.keyname())
    abuse_ref = api.entry_mark_as_spam(self.unpopular_ref,
                                       self.entry_ref.keyname())
    self.assertEqual(abuse_ref.entry, self.entry_ref.keyname())
    self.assertEqual(abuse_ref.actor, self.popular_nick)
    self.assertEqual(abuse_ref.reports, [self.unpopular_nick])
    # the count shouldn't increase just because the same user marks spam twice
    self.assertEqual(abuse_ref.count, 1)

  def test_entry_mark_as_spam_multiple_users(self):
    api.entry_mark_as_spam(self.unpopular_ref, self.entry_ref.keyname())
    abuse_ref = api.entry_mark_as_spam(self.celebrity_ref,
                                       self.entry_ref.keyname())
    self.assertEqual(abuse_ref.count, 2)
    self.assertEqual(set(abuse_ref.reports),
                     set([self.unpopular_nick, self.celebrity_nick]))

class ApiUnitTestAvatarUpload(ApiUnitTest):
  def setUp(self):
    super(ApiUnitTestAvatarUpload, self).setUp()
    with open('testdata/test_avatar.png') as avatar_file:
      self.avatar_file_content = avatar_file.read()

  def testResize(self):
    avatar_base_path = api.avatar_upload(self.popular,
                                         self.popular_nick,
                                         self.avatar_file_content)
    all_sizes = {'original': (320, 320)} # original dimension
    all_sizes.update(api.AVATAR_IMAGE_SIZES)
    for size, dimensions in all_sizes.items():
      keyname = 'image/%s_%s.jpg' % (avatar_base_path, size)
      image_ref = models.Image.get_by_key_name(keyname)
      self.assert_(image_ref)
      image = images.Image(image_ref.content)
      self.assertEqual(dimensions, (image.width, image.height))

  def testUploadInvalidImage(self):

    def _upload_invalid_image():
      api.avatar_upload(self.popular,
                        self.popular_nick,
                        'not an image')
    self.assertRaises(exception.ApiException, _upload_invalid_image)

class ApiUnitTestOAuthAccess(ApiUnitTest):
  def setUp(self):
    super(ApiUnitTestOAuthAccess, self).setUp()
    self.overrides = test_util.override(API_DISABLE_VERIFICATION=False,
                                        API_ALLOW_ROOT_HMAC_SHA1=False)

  def tearDown(self):
    self.overrides.reset()
    super(ApiUnitTestOAuthAccess, self).tearDown()

  def popular_request(self, url):
    consumer = oauth.OAuthConsumer('TESTDESKTOPCONSUMER', 'secret')
    access_token = oauth.OAuthToken('POPULARDESKTOPACCESSTOKEN', 'secret')
    url = 'http://%s%s' % (settings.DOMAIN, url)

    request = oauth.OAuthRequest.from_consumer_and_token(consumer,
                                                         access_token,
                                                         http_url=url)
    request.sign_request(oauth_util.HMAC_SHA1,
                         consumer,
                         access_token)
    return request

  def test_overview(self):
    request = self.popular_request('/user/popular/overview')
    r = self.client.get('/user/popular/overview', request.parameters)
    self.assertContains(r, "Hi popular! Here's the latest from your contacts")
    self.assertTemplateUsed(r, 'actor/templates/overview.html')

class ApiUnitTestActorGetContactsAvatarsSince(ApiUnitTest):
  def setUp(self):
    super(ApiUnitTestActorGetContactsAvatarsSince, self).setUp()
    self.celebrity = api.actor_get(api.ROOT, self.celebrity_nick)
    self.root = api.actor_get(api.ROOT, self.root_nick)

  def test_get_contacts_simple(self):
    result = api.actor_get_contacts_avatars_since(
        self.popular,
        self.popular_nick)
    self.assertEqual(3, len(result))
    self.assertEqual(self.celebrity_nick, result.pop(0).nick)
    self.assertEqual(self.popular_nick, result.pop(0).nick)
    self.assertEqual(self.root_nick, result.pop(0).nick)

  def test_get_contacts_with_limit(self):
    result = api.actor_get_contacts_avatars_since(
        self.popular,
        self.popular_nick,
        limit=1)
    self.assertEqual(1, len(result))
    self.assertEqual(self.popular_nick, result.pop(0).nick)

  def test_get_contacts_with_since_time(self):
    result = api.actor_get_contacts_avatars_since(
        self.popular,
        self.popular_nick,
        since_time='2005-01-01')
    self.assertEqual(2, len(result))
    self.assertEqual(self.celebrity_nick, result.pop(0).nick)
    self.assertEqual(self.root_nick, result.pop(0).nick)

  def test_get_contacts_with_limit_and_since_time(self):
    result = api.actor_get_contacts_avatars_since(
        self.popular,
        self.popular_nick,
        limit=1,
        since_time='2007-01-01')
    self.assertEqual(1, len(result))
    self.assertEqual(self.root_nick, result.pop(0).nick)

class EmailTest(ApiUnitTest):
  default_recipient = settings.DEFAULT_UNITTEST_TO_EMAIL

  def test_send_email(self):
    # Underlying Django's send_email method uses a mock object for SMTP server,
    # when running under tests.
    r = common_mail.send(self.default_recipient,
                         'Unit tests single email',
                         'Send at ' + str(datetime.datetime.now()))
    self.assertEquals(r, 1)

  def test_send_mass_email(self):
    subject = 'Unit tests mass email'
    message = 'Send at ' + str(datetime.datetime.now())

    recipients = [
        [self.default_recipient, 'teemu+unittest1@google.com'],
        [self.default_recipient]
        ]
    message_tuples = [(subject, message, 'root@example.com', r)
                      for r in recipients];
    r = common_mail.mass_send(message_tuples)

  # If a real email sending is not working in your environment,
  # comment out this test to test your setup.
  #def test_smtp_server(self):
  #  import smtplib
  #  from_addr = settings.DEFAULT_FROM_EMAIL
  #  to_addrs  = [settings.DEFAULT_FROM_EMAIL]
  #  msg = 'A Python standard library level email test, sent at ' + str(datetime.datetime.now())
  #  server = smtplib.SMTP('localhost')
  #  server.set_debuglevel(1)
  #  server.sendmail(from_addr, to_addrs, msg)
  #  server.quit()

  def test_email_confirmation_message(self):
    actor_with_name = api.actor_get(api.ROOT, self.celebrity_nick)
    (subject, message, html_message) = common_mail.email_confirmation_message(
        actor_with_name,
        '4124')
    self.assertTrue(message.count(actor_with_name.extra['given_name']) > 0)
    self.assertTrue(html_message.count(actor_with_name.extra['given_name']) > 0)

    actor_without_name = api.actor_get(api.ROOT, self.popular_nick)
    (subject, message, html_message) = common_mail.email_confirmation_message(
        actor_without_name, 
        '4124')
    self.assertTrue(message.count(actor_without_name.display_nick()) > 0)
    self.assertTrue(html_message.count(actor_without_name.display_nick()) > 0)

class ImageErrorDecoratorTest(ApiUnitTest):
  """Tests the image error decorator transforms image error to api exception"""
  def _test_specific_error_message(self, callable, error_message):
    try:
      callable()
      self.fail("did not raise ApiException")
    except exception.ApiException, e:
      self.assertEquals(error_message, e.message)

  @staticmethod
  @api.catch_image_error
  def no_error():
    return True

  def test_no_error(self):
    self.assertTrue(ImageErrorDecoratorTest.no_error())

  @staticmethod
  @api.catch_image_error
  def large_image_error():
    raise images.LargeImageError()

  def test_large_image_error(self):
    self._test_specific_error_message(ImageErrorDecoratorTest.large_image_error,
        "Uploaded image size is too large")

  @staticmethod
  @api.catch_image_error
  def not_image_error():
    raise images.NotImageError()

  def test_not_image_error(self):
    self._test_specific_error_message(ImageErrorDecoratorTest.not_image_error,
        "Uploaded image is not in a recognized image format")

  @staticmethod
  @api.catch_image_error
  def generic_image_error():
    raise images.Error()

  def test_generic_image_error(self):
    self.assertRaises(exception.ApiException,
        ImageErrorDecoratorTest.generic_image_error)
