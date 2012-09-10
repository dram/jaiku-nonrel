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

from common import api
from common import exception
from common import mail as common_mail
from common import util
from common.protocol import pshb
from common.protocol import sms
from common.protocol import xmpp
from common.test import base

from django.core import mail

class NotificationTest(base.FixturesTestCase):
  """ tests as per the Notifications Design section of doc/design_funument.txt

   * Uu - A simple update posted in a User's stream (you're subscribed).
   * Uc - A simple update posted in a Channel's stream (you're subscribed).
   * Eu - An external feed update posted in a User's stream (you're
     subscribed).
   * Ec - An external feed update posted in a Channel's stream (you're
     subscribed).
   * Cu - A comment posted to a User's entry by a User whose comment stream
     you are subscribed to.
   * Cc - A comment posted to a Channel's entry by a User whose comment stream
     you are subscribed to.
   * Cs - A comment posted to an entry created by you.
   * Cx - A comment posted to an entry you have also commented on.

  oneliner: email[Cs, Cx]; sms[Cs, Cx, Uu, Uc]; im[Cs, Cx, Uu, Uc, Cu]
  
  """

  def setUp(self):
    super(NotificationTest, self).setUp()
    self.popular = api.actor_get(api.ROOT, 'popular@example.com')
    self.unpopular = api.actor_get(api.ROOT, 'unpopular@example.com')
    self.girlfriend = api.actor_get(api.ROOT, 'girlfriend@example.com')
    self.boyfriend = api.actor_get(api.ROOT, 'boyfriend@example.com')
    self.otherboyfriend = api.actor_get(api.ROOT, 'otherboyfriend@example.com')
    self.channel = api.channel_get(api.ROOT, '#popular@example.com')
    self.popular_entry = api.entry_get(
        api.ROOT, 'stream/popular@example.com/presence/12345')
    self.girlfriend_entry = api.entry_get(
        api.ROOT, 'stream/girlfriend@example.com/presence/16961')
    self.channel_entry = api.entry_get(
        api.ROOT, 'stream/#popular@example.com/presence/13345')
    self.pshb_endpoints = [x.target for x in api.pshb_get_firehoses(api.ROOT)
                           if x.state == 'subscribed']
  
  def clear_outboxes(self):
    mail.outbox = []
    xmpp.outbox = []

  # action helpers
  def post(self, actor_ref):
    entry_ref = api.post(actor_ref, nick=actor_ref.nick, message='test_message')
    self.exhaust_queue_any()
    return entry_ref

  def channel_post(self, actor_ref, channel_ref):
    entry_ref = api.channel_post(actor_ref,
                                 channel=channel_ref.nick,
                                 nick=actor_ref.nick,
                                 message='test_message')
    self.exhaust_queue_any()
    return entry_ref

  def comment(self, actor_ref, entry_ref):
    entry_ref = api.entry_add_comment(actor_ref,
                                      stream=entry_ref.stream,
                                      entry=entry_ref.keyname(),
                                      nick=actor_ref.nick,
                                      content='test_message')
    self.exhaust_queue_any()
    return entry_ref

  # formatting helpers
  def inboxes(self, actor, *endpoints):
    return ['inbox/%s/%s' % (actor, endpoint) for endpoint in endpoints]

  def presence(self, actor):
    return 'stream/%s/presence' % actor

  # A bunch of "slow but steady" implementations to check against
  def get_subscriptions_for_topic(self, topic):
    return [s.target for s in api.subscription_get_topic(api.ROOT, topic)]

  def get_restricted_subscriptions_for_topic(self, topic):
    return [s.target 
            for s in api.subscription_get_topic(api.ROOT, topic)
            if s.is_subscribed()]

  def get_actors_for_inboxes(self, inboxes):
    subscribers = [util.get_user_from_topic(inbox) for inbox in inboxes]
    subscribers = list(set(subscribers))
    subscribers_ref = api.actor_get_actors(api.ROOT, subscribers)
    subscribers_ref = [v for k, v in subscribers_ref.iteritems() if v]
    return subscribers_ref

  def get_im_for_inboxes(self, entry_ref, inboxes):
    subscribers_ref = self.get_actors_for_inboxes(inboxes)
    im_aliases = []
    for subscriber_ref in subscribers_ref:
      if not subscriber_ref.extra.get('im_notify'):
        continue
      im = api.im_get_actor(api.ROOT, subscriber_ref.nick)
      if not im:
        continue
      im_aliases.append(im.full())
    return set(im_aliases)

  def get_email_for_inboxes(self, entry_ref, inboxes):
    subscribers_ref = self.get_actors_for_inboxes(inboxes)
    email_aliases = []
    parent_entry_ref = api.entry_get_safe(api.ROOT, entry_ref.entry)
    owners = [entry_ref.owner, entry_ref.actor]
    if parent_entry_ref:
      owners.extend((parent_entry_ref.owner, parent_entry_ref.actor))

    for subscriber_ref in subscribers_ref:
      # Only email if you are directly involved in the stream
      if subscriber_ref.nick not in owners:
        exists = api.subscription_exists(
            api.ROOT,
            entry_ref.entry,
            'inbox/%s/overview' % subscriber_ref.nick)
        if not exists:
          continue
      if not subscriber_ref.extra.get('email_notify'):
        continue
      email = api.email_get_actor(api.ROOT, subscriber_ref.nick)
      if not email:
        continue
      actor_ref = api.actor_get(api.ROOT, entry_ref.actor)
      if subscriber_ref.nick == actor_ref.nick:
        continue
      email_aliases.append(email)
    return set(email_aliases)

  def check_inboxes_for_entry(self, entry_ref, expected):
    inboxes = api.inbox_get_all_for_entry(api.ROOT,
                                          entry_ref.stream,
                                          entry_ref.uuid,
                                          entry_ref.entry)
    
    #self.assertEqual(len(inboxes), len(set(inboxes)), 'duplicates: %s' % inboxes)
    self.assertSetEqual(set(expected), set(inboxes))
    for inbox in inboxes:
      actor_ref = api.actor_get(api.ROOT, util.get_user_from_topic(inbox))
      if not api.entry_get_safe(actor_ref, entry_ref.keyname()):
        self.fail('An entry not visible by a user was added to their inbox')
    return inboxes

  def check_im_for_inboxes(self, entry_ref, inboxes):
    # entry_ref is unused
    im_aliases = self.get_im_for_inboxes(entry_ref, inboxes)
    if len(im_aliases) > 0:
      self.assertSetEqual(im_aliases, set([x[0].full() for x in xmpp.outbox]))
    else:
      self.fail('Bad test, no IM to check out of:\n%s' % '\n'.join(inboxes))

  def check_email_for_inboxes(self, entry_ref, inboxes):
    if not entry_ref.entry:
      self.assertEqual(0, len(mail.outbox), 'no email for posts')
      return

    email_aliases = self.get_email_for_inboxes(entry_ref, inboxes)
    if len(email_aliases) > 0:
      self.assertSetEqual(email_aliases, set([x.to[0] for x in mail.outbox]))
    else:
      self.fail('Bad test, no email to check out of:\n%s' % '\n'.join(inboxes))

  def check_pshb_for_entry(self, entry_ref):
    if entry_ref.is_comment():
      self.assertEqual(0, len(pshb.outbox), 'no pshb for comments')
      return
    if entry_ref.is_channel():
      self.assertEqual(0, len(pshb.outbox), 'no pshb for channels (yet)')
      return
    owner_ref = api.actor_get(api.ROOT, entry_ref.owner)
    feed_url = owner_ref.url('/atom')
    check = set([(endpoint, (feed_url,)) for endpoint in self.pshb_endpoints])
    if len(check) > 0:
      self.assertSetEqual(check, set(pshb.outbox))
    else:
      self.fail('Bad test, no pshb to check')

  def test_public_to_own_public(self):
    """post by public user to own public stream
     who should see this:
       - the user who posted * overview, private, contacts, public
       - users subscribed to user's stream * overview
       - explore
     except:
       - no email about posts
    """
    actor = self.popular.nick
    subscriptions = self.inboxes(
        actor, 'overview', 'private', 'contacts', 'public')
    subscriptions += self.get_subscriptions_for_topic(self.presence(actor))
    subscriptions += ['inbox/%s/explore' % api.ROOT.nick]
    subscriptions = list(set(subscriptions))

    entry_ref = self.post(self.popular)

    self.check_inboxes_for_entry(entry_ref, subscriptions)
    self.check_email_for_inboxes(entry_ref, subscriptions)
    self.check_im_for_inboxes(entry_ref, subscriptions)
    self.check_pshb_for_entry(entry_ref)
  
  def test_contactsonly_to_own_contactsonly(self):
    """post by contacts-only user to own contacts-only stream
     who should see this:
       - users subscribed to user's restricted stream * overview
       - the user who posted * overview, private, contacts
     except:
       - no email about posts
    """
    actor = self.girlfriend.nick
    subscriptions = self.inboxes(
        actor, 'overview', 'private', 'contacts')
    subscriptions += self.get_restricted_subscriptions_for_topic(
        self.presence(actor))
    subscriptions = list(set(subscriptions))

    entry_ref = self.post(self.girlfriend)

    self.check_inboxes_for_entry(entry_ref, subscriptions)
    self.check_email_for_inboxes(entry_ref, subscriptions)
    self.check_im_for_inboxes(entry_ref, subscriptions)
    self.check_pshb_for_entry(entry_ref)
  
  def test_contactsonly_to_public_channel(self):
    """post by public user to public channel
     who should see this:
       - users subscribed to the channel's stream * overview
       - the user who posted * overview, private
       - the channel posted to * private, contacts, public
     except:
       - no email about posts
    """
    actor = self.popular.nick
    # TODO(termie): the below should include private
    subscriptions = self.inboxes(
        actor, 'overview')
    subscriptions = self.inboxes(
        self.channel.nick, 'private', 'contacts', 'public')
    subscriptions += self.get_subscriptions_for_topic(
        self.presence(self.channel.nick))
    subscriptions = list(set(subscriptions))

    entry_ref = self.channel_post(self.popular, self.channel)

    self.check_inboxes_for_entry(entry_ref, subscriptions)
    self.check_email_for_inboxes(entry_ref, subscriptions)
    self.check_im_for_inboxes(entry_ref, subscriptions)
    self.check_pshb_for_entry(entry_ref)

  def test_public_to_public_channel(self):
    """post by contactsonly user to public channel
     who should see this:
       - users subscribed to the channel's stream * overview
       - the user who posted * overview, private
       - the channel posted to * private, contacts, public
     except:
       - no email about posts
    """
    actor = self.popular.nick
    # TODO(termie): the below should include private
    subscriptions = self.inboxes(
        actor, 'overview')
    subscriptions = self.inboxes(
        self.channel.nick, 'private', 'contacts', 'public')
    subscriptions += self.get_subscriptions_for_topic(
        self.presence(self.channel.nick))
    subscriptions = list(set(subscriptions))

    entry_ref = self.channel_post(self.popular, self.channel)

    self.check_inboxes_for_entry(entry_ref, subscriptions)
    self.check_email_for_inboxes(entry_ref, subscriptions)
    self.check_im_for_inboxes(entry_ref, subscriptions)
    self.check_pshb_for_entry(entry_ref)

  def test_public_comment_to_own_public_entry(self):
    """comment by public user on own public entry
     who should see this:
       - the user who commented * overview, private, contacts, public
       - the entry that was commented on * comments
       - users subscribed to the entry commented on * overview
       - users who follow commenting user's comment stream * overview
     except:
       - no email about own comments
    """
    actor = self.popular.nick
    comments_stream = self.popular_entry.keyname() + '/comments'
    subscriptions = self.inboxes(
        actor, 'overview', 'private', 'contacts', 'public')
    subscriptions += [comments_stream]
    subscriptions += self.get_subscriptions_for_topic(
        self.popular_entry.keyname())
    subscriptions += self.get_subscriptions_for_topic(
        'stream/%s/comments' % actor)
    subscriptions = list(set(subscriptions))

    entry_ref = self.comment(self.popular, self.popular_entry)

    self.check_inboxes_for_entry(entry_ref, subscriptions)
    self.check_email_for_inboxes(entry_ref, subscriptions)
    self.check_im_for_inboxes(entry_ref, subscriptions)
    self.check_pshb_for_entry(entry_ref)

  def test_public_comment_to_other_public_entry(self):
    """comment by public user on other public user's entry
     who should see this:
       - the user who commented * overview, private, contacts, public
       - the user who was commented on * overview
       - the entry that was commented on * comments
       - users subscribed to the entry commented on * overview
       - users who follow commenting user's comment stream * overview
     except:
       - no email about own comments
    """
    actor = self.unpopular.nick
    comments_stream = self.popular_entry.keyname() + '/comments'
    subscriptions = self.inboxes(
        actor, 'overview', 'private', 'contacts', 'public')
    subscriptions += self.inboxes(self.popular.nick, 'overview')
    subscriptions += [comments_stream]
    subscriptions += self.get_subscriptions_for_topic(
        self.popular_entry.keyname())
    subscriptions += self.get_subscriptions_for_topic(
        'stream/%s/comments' % actor)
    subscriptions = list(set(subscriptions))

    entry_ref = self.comment(self.unpopular, self.popular_entry)

    self.check_inboxes_for_entry(entry_ref, subscriptions)
    self.check_email_for_inboxes(entry_ref, subscriptions)
    self.check_im_for_inboxes(entry_ref, subscriptions)
    self.check_pshb_for_entry(entry_ref)

  def test_public_comment_to_contactsonly_entry(self):
    """comment by public user on contacts-only user's entry
     who should see this:
       - the user who commented * overview, private, [contacts, overview]
       - the user who was commented on * overview
       - the entry that was commented on * comments
       - users subscribed to t    if not key_name and :
      key_name = self.key().name()
he entry's restricted stream * overview
     except:
       - no email about own comments
    """
    actor = self.boyfriend.nick
    comments_stream = self.girlfriend_entry.keyname() + '/comments'
    subscriptions = self.inboxes(actor, 'overview', 'private')
    # TODO(termie): I'm on the fence with these two, the visibility on the 
    #               entry itself will prevent it from being show where it
    #               it shouldn't, but it still seems weird to put it in public
    subscriptions += self.inboxes(actor, 'contacts', 'public')
    subscriptions += self.inboxes(
        self.girlfriend.nick, 'overview')
    subscriptions += [comments_stream]
    subscriptions += self.get_restricted_subscriptions_for_topic(
        self.girlfriend_entry.keyname())
    subscriptions += self.get_restricted_subscriptions_for_topic(
        'stream/%s/comments' % actor)
    subscriptions = list(set(subscriptions))

    entry_ref = self.comment(self.boyfriend, self.girlfriend_entry)

    self.check_inboxes_for_entry(entry_ref, subscriptions)
    self.check_email_for_inboxes(entry_ref, subscriptions)
    self.check_im_for_inboxes(entry_ref, subscriptions)
    self.check_pshb_for_entry(entry_ref)

  def test_public_comment_to_own_public_channel_entry(self):
    """comment by public user on own public channel's entry
     who should see this:
       - the user who commented * overview, private
       - the entry that was commented on * comments
       - the users subscribed to the entry's stream * overview
     except:
       - no email about own comments
    """
    actor = self.popular.nick
    comments_stream = self.channel_entry.keyname() + '/comments'
    subscriptions = self.inboxes(
        actor, 'overview', 'private')
    subscriptions += [comments_stream]
    subscriptions += self.get_subscriptions_for_topic(
        self.channel_entry.keyname())
    # TODO(termie): I feel that this is the wrong behavior, but it is
    #               the currently accepted behavior, changes to current
    #               behavior should make make this test break and hopefully
    #               we can remove this to fix it
    subscriptions += self.get_subscriptions_for_topic(
        'stream/%s/comments' % actor)
    subscriptions = list(set(subscriptions))

    # TODO(termie): Add this to the fixtures instead of adding at runtime here
    self.comment(self.unpopular, self.channel_entry)
    self.clear_outboxes()
    entry_ref = self.comment(self.popular, self.channel_entry)

    self.check_inboxes_for_entry(entry_ref, subscriptions)
    self.check_email_for_inboxes(entry_ref, subscriptions)
    self.check_im_for_inboxes(entry_ref, subscriptions)
    self.check_pshb_for_entry(entry_ref)

  def test_public_comment_to_public_channel_entry(self):
    """comment by public user on public channel's entry
     who should see this:
       - the user who commented * overview, private
       - the user who was commented on * overview
       - the entry that was commented on * comments
       - the users subscribed to the entry's stream * overview
     except:
       - no email about own comments
    """
    actor = self.unpopular.nick
    comments_stream = self.channel_entry.keyname() + '/comments'
    subscriptions = self.inboxes(
        actor, 'overview', 'private')
    subscriptions += self.inboxes(self.popular.nick, 'overview')
    subscriptions += [comments_stream]
    subscriptions += self.get_subscriptions_for_topic(
        self.channel_entry.keyname())
    # TODO(termie): I feel that this is the wrong behavior, but it is
    #               the currently accepted behavior, changes to current
    #               behavior should make make this test break and hopefully
    #               we can remove this to fix it
    subscriptions += self.get_subscriptions_for_topic(
        'stream/%s/comments' % actor)
    subscriptions = list(set(subscriptions))
    
    entry_ref = self.comment(self.unpopular, self.channel_entry)

    self.check_inboxes_for_entry(entry_ref, subscriptions)
    self.check_email_for_inboxes(entry_ref, subscriptions)
    self.check_im_for_inboxes(entry_ref, subscriptions)
    self.check_pshb_for_entry(entry_ref)
  
  def test_contactsonly_comment_to_public_entry(self):
    """comment by contacts-only user on public user's entry
     who should see this:
       - the user who commented * overview, private
       - the user who was commented on * overview
       - the entry that was commented on * comments
       - users subscribe to the restricted user's comment stream * overview
       - users subscribe to the entry's comment stream * overview
     except:
       - no email about own comments
    """
    actor = self.girlfriend.nick
    comments_stream = self.popular_entry.keyname() + '/comments'
    subscriptions = self.inboxes(
        actor, 'overview', 'private')
    subscriptions += self.inboxes(self.popular.nick, 'overview')
    subscriptions += [comments_stream]
    subscriptions += self.get_restricted_subscriptions_for_topic(
        'stream/%s/comments' % actor)
    subscriptions += self.get_subscriptions_for_topic(
        self.popular_entry.keyname())
    subscriptions = list(set(subscriptions))

    entry_ref = self.comment(self.girlfriend, self.popular_entry)

    self.check_inboxes_for_entry(entry_ref, subscriptions)
    self.check_email_for_inboxes(entry_ref, subscriptions)
    self.check_im_for_inboxes(entry_ref, subscriptions)
    self.check_pshb_for_entry(entry_ref)

  def test_contactsonly_comment_to_own_contactsonly_entry(self):
    """comment by contacts-only user on own contacts-only user's entry
     who should see this:
       - the user who commented * overview, private
       - the entry that was commented on * comments
       - the users subscribed to the entry's restricted stream * overview
     except:
       - no email about own comments
    """
    actor = self.girlfriend.nick
    comments_stream = self.girlfriend_entry.keyname() + '/comments'
    subscriptions = self.inboxes(
        actor, 'overview', 'private')
    subscriptions += [comments_stream]
    subscriptions += self.get_restricted_subscriptions_for_topic(
        'stream/%s/comments' % actor)
    subscriptions += self.get_restricted_subscriptions_for_topic(
        self.girlfriend_entry.keyname())
    subscriptions = list(set(subscriptions))

    entry_ref = self.comment(self.girlfriend, self.girlfriend_entry)

    self.check_inboxes_for_entry(entry_ref, subscriptions)
    self.check_email_for_inboxes(entry_ref, subscriptions)
    self.check_im_for_inboxes(entry_ref, subscriptions)
    self.check_pshb_for_entry(entry_ref)

  def test_contactsonly_comment_to_other_contactsonly_entry(self):
    """comment by contacts-only user on other contacts-only user's entry
     who should see this:
       - the user who commented * overview, private
       - the user who was commented on * overview
       - the entry that was commented on * comments
       - the users subscribed to the entry's restricted stream * overview
     except:
       - no email about own comments
    """
    actor = self.otherboyfriend.nick
    comments_stream = self.girlfriend_entry.keyname() + '/comments'
    subscriptions = self.inboxes(
        actor, 'overview', 'private')
    subscriptions += self.inboxes(
        self.girlfriend.nick, 'overview')
    subscriptions += [comments_stream]
    subscriptions += self.get_restricted_subscriptions_for_topic(
        'stream/%s/comments' % actor)
    subscriptions += self.get_subscriptions_for_topic(
        self.girlfriend_entry.keyname())
    subscriptions = list(set(subscriptions))

    entry_ref = self.comment(self.otherboyfriend, self.girlfriend_entry)

    self.check_inboxes_for_entry(entry_ref, subscriptions)
    self.check_email_for_inboxes(entry_ref, subscriptions)
    self.check_im_for_inboxes(entry_ref, subscriptions)
    self.check_pshb_for_entry(entry_ref)

  def test_contactsonly_comment_to_public_channel_entry(self):
    """comment by contacts-only user on public channel's entry
     who should see this:
       - the user who commented * overview, private
       - the user who was commented on * overview
       - the entry that was commented on * comments
       - the users subscribed to the entry's stream * overview
     except:
       - no email about own comments
    """
    actor = self.girlfriend.nick
    comments_stream = self.channel_entry.keyname() + '/comments'
    subscriptions = self.inboxes(
        actor, 'overview', 'private')
    subscriptions += self.inboxes(self.popular.nick, 'overview')
    subscriptions += [comments_stream]
    subscriptions += self.get_subscriptions_for_topic(
        self.channel_entry.keyname())
    # TODO(termie): I feel that this is the wrong behavior, but it is
    #               the currently accepted behavior, changes to current
    #               behavior should make make this test break and hopefully
    #               we can remove this to fix it
    subscriptions += self.get_restricted_subscriptions_for_topic(
        'stream/%s/comments' % actor)
    subscriptions = list(set(subscriptions))
    
    entry_ref = self.comment(self.girlfriend, self.channel_entry)

    self.check_inboxes_for_entry(entry_ref, subscriptions)
    self.check_email_for_inboxes(entry_ref, subscriptions)
    self.check_im_for_inboxes(entry_ref, subscriptions)
    self.check_pshb_for_entry(entry_ref)

