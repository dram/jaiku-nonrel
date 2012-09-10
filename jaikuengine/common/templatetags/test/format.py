# -*- coding: utf-8 -*-
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

from django import test

from common import exception
from common import models
from common import util
from common.templatetags import format
from common.test import base
from common.test import util as test_util


class FormatTest(test.TestCase):
  def assertLinkTransformed(self, value):
    expected = """<a href="%s" target="_new">%s</a>""" % (value, value)
    self.assertEqual(expected, format.format_autolinks(value))
  
  def assertLinkNotTransformed(self, value):
    self.assertEqual(value, format.format_autolinks(value))

  def test_truncate(self):
    test_strings = [(u"Testing", 7, u"Testing"),
                    ("Testing", 6, u"Testin\u2026"),
                    (u"åäöåäöåäöåäö", 10, u"åäöåäöåäöå…")]

    for orig_str, max_len, trunc_str in test_strings:
      a = format.truncate(orig_str, max_len)
      self.assertEqual(a, trunc_str)

  def test_format_transforms_valid_links(self):
    # We should accept links that start with http
    self.assertLinkTransformed('http://example.com')
    self.assertLinkTransformed('http://example.com/')
    self.assertLinkTransformed('http://www.example.com')
    self.assertLinkTransformed('http://www.example.com/~someuser')
    self.assertLinkTransformed('http://www.example.com/a/b/c/d/e/f/g')
    self.assertLinkTransformed('https://example.com')
    self.assertLinkTransformed('https://example.com/')
    self.assertLinkTransformed('https://www.example.com')
    self.assertLinkTransformed('https://www.example.com/~someuser')
    self.assertLinkTransformed('https://www.example.com/a/b/c/d/e/f/g')

  def test_format_ignores_invalid_links(self):
    # Any link that doesn't start with http should be ignored
    # otherwise we run the risk of security problems from data: and javascript: links
    self.assertLinkNotTransformed("""javascript:document.location="http://localhost:8080/?evil=" """ )
    self.assertLinkNotTransformed('''javascript:document.location="http://localhost:8080/?evil="''')
    self.assertLinkNotTransformed('''data:text/html;base64,PHNjcmlwdD5hbGVydChkb2N1bWVudC5jb29raWUpPC9zY3JpcHQ+Cg==''')


class FormatFixtureTest(base.FixturesTestCase):

  # TODO(jonasnockert): Improve test method... but how?
  def test_linked_entry_truncated_title(self):
    # Get all StreamEntries to make sure both posts and comments are
    # tested.
    entries = models.StreamEntry.all()

    for e in entries:
      # Truncate to one character to ensure truncation takes place and
      # an ellipsis is added. 
      trunc_url = format.linked_entry_truncated_title(e, 1)
      # Construct a link with made-up one character+ellipsis entry title.
      trunc_ref_url = u"<a href=\"%s\">x\u2026</a>" % e.url()
      self.assertEqual(len(trunc_url), len(trunc_ref_url))
