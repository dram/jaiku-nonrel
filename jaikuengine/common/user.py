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

import datetime
import logging

from appengine_django.sessions.models import Session
from django.conf import settings
from google.appengine.ext import db
import oauth.oauth as oauth

from common import api
from common import exception
from common import legacy
from common import oauth_util
from common import util


def get_user_from_request(request):
  """attempt to get a logged in user based on the request
  
  most likely from a cookie
  """   
  nick = request.COOKIES.get(settings.USER_COOKIE, None)
  token = request.COOKIES.get(settings.PASSWORD_COOKIE, None)
  if nick:
    # try to authenticate the dude via cookie
    user = authenticate_user_cookie(nick, token)
    return user

  if (settings.API_ALLOW_LEGACY_AUTH 
      and 'personal_key' in request.REQUEST 
      and 'user' in request.REQUEST):
    user = legacy.authenticate_user_personal_key(
        request.REQUEST['user'], request.REQUEST['personal_key'])
    if user:
      user.legacy = True
    return user


  # we may not be authenticating via cookie, check oauth also
  # Note: This will have the effect that any valid OAuth request
  #       will effectively be treated as a logged in user with one
  #       small difference, api users (via OAuth, etc) are given
  #       a permission level of read, write or delete which limits
  #       what they are able to do on the site.
  if (('oauth_token' in request.REQUEST and 'oauth_consumer_key' in request.REQUEST) 
      or 'HTTP_AUTHORIZATION' in request.META):
    oauth_util.verify_request(request)
    user = oauth_util.get_api_user(request)
    return user

  return None

def purge_expired_user_auth_token_keys():
  """ Remove expired tokens from the database. """

  #TODO: Remove hard coded limit
  limit = 10
  try:
    query = Session.gql("WHERE expire_date <= :1", api.utcnow())
    expired_tokens = query.count()
    if expired_tokens:
      db.delete(query.fetch(limit))
      logging.info("Removed %d expired user authentication "
                   "tokens (%d remaining)",
                   min(limit, expired_tokens),
                   max(0, expired_tokens-limit))
  except Exception, e:
    logging.exception('Unhandled exception while removing expired tokens')
  return

def generate_user_auth_token_key(nick, token):
  return "user_auth_token/%s/%s" % (nick, token)

def lookup_user_auth_token(nick, token):
  """ Look up a user authentication token from the database cache. """

  key = generate_user_auth_token_key(nick, token)
  user_auth_token_blob = Session.get_by_key_name(key)
  if not user_auth_token_blob:
    return None
  elif user_auth_token_blob.expire_date <= api.utcnow():
    return None
  else:
    user_auth_token = user_auth_token_blob.session_data.decode("utf-8")
    return user_auth_token

def generate_user_auth_token(nick,
                             password,
                             timeout=(14 * 24 * 60 * 60)):
  """ Generates a user authentication token and stores it in the
  database for later retrieval.

  Why store tokens in the database? Because GAE flushes memcache quite
  aggressively and this was causing users to be logged out much more
  frequently than was acceptable.

  """
  # Clear cache of expired tokens
  purge_expired_user_auth_token_keys()

  token = util.hash_generic(util.generate_uuid())
  key = generate_user_auth_token_key(nick, token)
  # Set an expiration date to enable us to purge old, inactive
  # sessions from the database. Cookie expiration dates are what
  # actually govern how long sessions last.
  expire_date = (api.utcnow() +
                 datetime.timedelta(seconds=timeout))
  session = Session(key_name=key,
                    session_data=db.Blob(password.encode("utf-8")),
                    expire_date=expire_date)
  session.put()
  return token

def authenticate_user_cookie(nick, token):
  user = api.actor_get_safe(api.ROOT, nick)
  if not user:
    return None

  # user's authenticated via cookie have full access
  user.access_level = api.DELETE_ACCESS

  cached_token = lookup_user_auth_token(user.nick, token)
  if not cached_token:
    return None

  if user.password != cached_token:
    return None

  return user

def authenticate_user_login(nick, password):
  user = api.actor_lookup_nick(api.ROOT, nick)
  if not user:
    return None

  # user's authenticated via login have full access
  user.access_level = api.DELETE_ACCESS

  if settings.DEBUG and password == "password":
    return user

  if user.password == util.hash_password(user.nick, password):
    return user

  # we're changing the password hashing, this will update their password
  # to their new format
  # TODO(termie): The settings.MANAGE_PY stuff below is so that the tests
  #               will continue to work with fixtures that have the passwords
  #               in clear text. We should probably remove this and change
  #               the passwords in the fixtures to be the legacy-style
  #               passwords.
  if (user.password == util.hash_password_intermediate(user.nick, password)
      or settings.MANAGE_PY and user.password == password):
    logging.debug("updating password for intermediate user: %s", user.nick)
    user = api.actor_update_intermediate_password(api.ROOT,
                                                  user.nick,
                                                  password)

    # a little repeat of above since we have a new user instance now
    user.access_level = api.DELETE_ACCESS
    
    return user
  return None


def lookup_user_by_login(login, password):
  """Looks up user by a given login. Returns None on failure.

    login - can be either nick or confirmed email
    password - password associated withe the user
  """
  try:
    current_user = authenticate_user_login(login, password)
    if current_user:
      return current_user
  except exception.ValidationError:
    pass # let's try the email address next
  # login can be confirmed email address
  actor_ref = api.actor_lookup_email(api.ROOT, login)
  if actor_ref:
    return authenticate_user_login(actor_ref.nick, password)
  return None


def set_user_cookie(response, user, remember=False):
  # We set max-age (because that's what HTTP 1.1 requires
  # We set expires because IE6/IE7/IE8 don't support max-age
  # We set both to be safe. 
  if remember:
    two_weeks = datetime.datetime.utcnow() + datetime.timedelta(days=14)
    expires = two_weeks.strftime("%a, %d-%b-%y %H:%M:%S GMT")
    max_age_delta = 14 * (60 * 60 * 24)
  else:
    expires = None
    max_age_delta = None

  auth_token = generate_user_auth_token(user.nick, user.password)

  if settings.COOKIE_DOMAIN == "localhost":
    response.set_cookie(settings.USER_COOKIE, 
                        user.nick, 
                        expires=expires, 
                        path=settings.COOKIE_PATH,
                        max_age=max_age_delta)
    response.set_cookie(settings.PASSWORD_COOKIE,
                        auth_token, 
                        expires=expires, 
                        path=settings.COOKIE_PATH,
                        max_age=max_age_delta)
  else:
    response.set_cookie(settings.USER_COOKIE, 
                        user.nick, 
                        expires=expires, 
                        path=settings.COOKIE_PATH, 
                        domain=settings.COOKIE_DOMAIN,
                        max_age=max_age_delta)
    response.set_cookie(settings.PASSWORD_COOKIE, 
                        auth_token, 
                        expires=expires, 
                        path=settings.COOKIE_PATH, 
                        domain=settings.COOKIE_DOMAIN,
                        max_age=max_age_delta)

  return response

def clear_user_cookie(response):
  if settings.COOKIE_DOMAIN == "localhost":
    response.delete_cookie(settings.USER_COOKIE, path=settings.COOKIE_PATH)
    response.delete_cookie(settings.PASSWORD_COOKIE, path=settings.COOKIE_PATH)
  else:
    response.delete_cookie(settings.USER_COOKIE, 
                           path=settings.COOKIE_PATH, 
                           domain=settings.COOKIE_DOMAIN)
    response.delete_cookie(settings.PASSWORD_COOKIE, 
                           path=settings.COOKIE_PATH, 
                           domain=settings.COOKIE_DOMAIN)

  return response
