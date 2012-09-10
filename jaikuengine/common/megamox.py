
from mox import *
import stubout


# Some hacks to make Mox work a bit better with JaikuEngine tests

import logging

class Stubber(object):
  __set = True
  def __init__(self, stubs):
    self.stubs = stubs

  def Unset(self):
    if self.__set:
      setattr(self.parent, self.child_name, self.old_child)
      self.__set = False

  def Set(self, parent, child_name, new_child):
    self.stubs.Set(parent, child_name, new_child)
    
    # hack for now, we're going to pop and re-append coolness
    (parent, old_child, child_name) = self.stubs.cache.pop()

    self.parent = parent
    self.old_child = old_child
    self.child_name = child_name
    self.__set = True

    self.stubs.cache.append(self)
    return self

class ExtendedStubOut(stubout.StubOutForTesting):
  def GetStubber(self):
    return Stubber(self) 
  
  def UnsetAll(self):
    self.cache.reverse()
    for stubbed_out in self.cache:
      if hasattr(stubbed_out, 'Unset'):
        stubbed_out.Unset()
        continue
      (parent, old_child, child_name) = stubbed_out
      setattr(parent, child_name, old_child)
    self.cache = []

class ExtendedMockMethod(MockMethod):
  def __init__(self, method_name, call_queue, replay_mode,
               method_to_mock=None, description=None, stub=None):
    super(ExtendedMockMethod, self).__init__(
        method_name, call_queue, replay_mode)
    self._stub = stub
    self._once = False

  def _PopNextMethod(self):
    try:
      call = self._call_queue.popleft()
      if call._once and call._stub:
        self._stub.Unset()
      return call
    except IndexError:
      raise mox.UnexpectedMethodCallError(self, None)

  def Once(self):
    self._once = True
    return self

class ExtendedMox(Mox):
  def __init__(self, *args, **kw):
    super(ExtendedMox, self).__init__(*args, **kw)
    self.stubs = ExtendedStubOut()

  def StubOutWithMock(self, obj, attr_name, use_mock_anything=False):
    """Replace a method, attribute, etc. with a Mock.

    This will replace a class or module with a MockObject, and everything else
    (method, function, etc) with a MockAnything.  This can be overridden to
    always use a MockAnything by setting use_mock_anything to True.

    Args:
      obj: A Python object (class, module, instance, callable).
      attr_name: str.  The name of the attribute to replace with a mock.
      use_mock_anything: bool. True if a MockAnything should be used regardless
        of the type of attribute.
    """
    attr_to_replace = getattr(obj, attr_name)

    # Check for a MockAnything. This could cause confusing problems later on.
    if attr_to_replace == MockAnything():
      raise TypeError('Cannot mock a MockAnything! Did you remember to '
                      'call UnsetStubs in your previous test?')
    
    stubbed_out = self.stubs.GetStubber()
    
    if type(attr_to_replace) in self._USE_MOCK_OBJECT and not use_mock_anything:
      stub = self.CreateMock(attr_to_replace, stub=stubbed_out)
    else:
      stub = self.CreateMockAnything(
          description='Stub for %s' % attr_to_replace,
          stub=stubbed_out)
    
    stubbed_out.Set(obj, attr_name, stub)
    

  def CreateMock(self, class_to_mock, stub=None):
    mock = super(ExtendedMox, self).CreateMock(class_to_mock)
    self._CurryMockWithStubbedOut(mock, stub)
    return mock

  def CreateMockAnything(self, description=None, stub=None):
    mock = super(ExtendedMox, self).CreateMockAnything()
    self._CurryMockWithStubbedOut(mock, stub)
    return mock

  def _CurryMockWithStubbedOut(self, mock, stubbed_out):
    def _CurriedCreateMockMethod(method_name, method_to_mock=None):
      return ExtendedMockMethod(method_name, 
                                mock._expected_calls_queue,
                                mock._replay_mode, 
                                method_to_mock=method_to_mock,
                                stub=stubbed_out)

    mock._CreateMockMethod = _CurriedCreateMockMethod

