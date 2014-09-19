# -*- coding: utf-8 -*-

import sys
import functools
import inspect
import re
import copy
import itertools
import numbers
import pkg_resources


# Python3 support
py3 = sys.version_info[0] == 3
if py3:
    import urllib.parse as urlparse
    str_types = (str, bytes)
    unicode = str
else:
    try:
        from future_builtins import map
    except ImportError:
        # Support for GAE runner
        from itertools import imap as map
    import urlparse
    str_types = (basestring,)

"""
Trafaret is tiny library for data validation
It provides several primitives to validate complex data structures
Look at doctests for usage examples
"""

__all__ = ("DataError", "Trafaret", "Any", "Int", "String",
           "List", "Dict", "Or", "Null", "Float", "Enum", "Callable",
           "Call", "Forward", "Bool", "Type", "Mapping", "guard", "Key",
           "Tuple", "Atom", "Email", "URL")

ENTRY_POINT = 'trafaret'
_empty = object()

def py3metafix(cls):
    if not py3:
        return cls
    else:
        newcls = cls.__metaclass__(cls.__name__, (cls,), {})
        newcls.__doc__ = cls.__doc__
        return newcls


class DataError(ValueError):

    """
    Error with data preserve
    error can be a message or None if error raised in childs
    data can be anything
    """

    def __init__(self, error=None, name=None):
        self.error = error
        self.name = name

    def __str__(self):
        return str(self.error)

    def __repr__(self):
        return 'DataError(%s)' % str(self)

    def as_dict(self):
        def as_dict(dataerror):
            if not isinstance(dataerror.error, dict):
                return self.error
            return dict((k, v.as_dict() if isinstance(v, DataError) else v)
                        for k, v in dataerror.error.items())
        return as_dict(self)


class TrafaretMeta(type):

    """
    Metaclass for trafarets to make using "|" operator possible not only
    on instances but on classes

    >>> Int | String
    <Or(<Int>, <String>)>
    >>> Int | String | Null
    <Or(<Int>, <String>, <Null>)>
    >>> (Int >> (lambda v: v if v ** 2 > 15 else 0)).check(5)
    5
    """

    def __or__(cls, other):
        return cls() | other

    def __rshift__(cls, other):
        return cls() >> other


@py3metafix
class Trafaret(object):

    """
    Base class for trafarets, provides only one method for
    trafaret validation failure reporting

    Check that converters can be stacked
    >>> (Int() >> (lambda x: x * 2) >> (lambda x: x * 3)).check(1)
    6

    Check order
    >>> (Int() >> float >> str).check(4)
    '4.0'
    """

    __metaclass__ = TrafaretMeta

    def check(self, value):
        """
        Common logic. In subclasses you need to implement check_value or
        check_and_return.
        """
        if hasattr(self, 'check_value'):
            self.check_value(value)
            return self._convert(value)
        if hasattr(self, 'check_and_return'):
            return self._convert(self.check_and_return(value))
        cls = "%s.%s" % (type(self).__module__, type(self).__name__)
        raise NotImplementedError("You must implement check_value or"
                                  " check_and_return methods '%s'" % cls)

    def converter(self, value):
        """
        You can change converter with `>>` operator or append method
        """
        return value

    def _convert(self, value):
        val = value
        for converter in getattr(self, 'converters', [self.converter]):
            val = converter(val)
        return val

    def _failure(self, error=None):
        """
        Shortcut method for raising validation error
        """
        raise DataError(error=error)

    def _trafaret(self, trafaret):
        """
        Helper for complex trafarets, takes trafaret instance or class
        and returns trafaret instance
        """
        if isinstance(trafaret, Trafaret) or inspect.isroutine(trafaret):
            return trafaret
        elif issubclass(trafaret, Trafaret):
            return trafaret()
        elif isinstance(trafaret, type):
            return Type(trafaret)
        else:
            raise RuntimeError("%r should be instance or subclass"
                               " of Trafaret" % trafaret)

    def append(self, converter):
        """
        Appends new converter to list.
        """
        if hasattr(self, 'converters'):
            self.converters.append(converter)
        else:
            self.converters = [converter]
        return self

    def __or__(self, other):
        return Or(self, other)

    def __rshift__(self, other):
        self.append(other)
        return self

    def __call__(self, val):
        return self.check(val)


class TypeMeta(TrafaretMeta):

    def __getitem__(self, type_):
        return self(type_)


@py3metafix
class Type(Trafaret):

    """
    >>> Type(int)
    <Type(int)>
    >>> Type[int]
    <Type(int)>
    >>> c = Type[int]
    >>> c.check(1)
    1
    >>> extract_error(c, "foo")
    'value is not int'
    """
    __metaclass__ = TypeMeta

    def __init__(self, type_):
        self.type_ = type_

    def check_value(self, value):
        if not isinstance(value, self.type_):
            self._failure("value is not %s" % self.type_.__name__)

    def __repr__(self):
        return "<Type(%s)>" % self.type_.__name__


class Any(Trafaret):

    """
    >>> Any()
    <Any>
    >>> (Any() >> ignore).check(object())
    """

    def check_value(self, value):
        pass

    def __repr__(self):
        return "<Any>"


class OrMeta(TrafaretMeta):

    """
    Allows to use "<<" operator on Or class

    >>> Or << Int << String
    <Or(<Int>, <String>)>
    """

    def __lshift__(cls, other):
        return cls() << other


@py3metafix
class Or(Trafaret):

    """
    >>> nullString = Or(String, Null)
    >>> nullString
    <Or(<String>, <Null>)>
    >>> nullString.check(None)
    >>> nullString.check("test")
    'test'
    >>> extract_error(nullString, 1)
    {0: 'value is not a string', 1: 'value should be None'}
    """

    __metaclass__ = OrMeta

    def __init__(self, *trafarets):
        self.trafarets = list(map(self._trafaret, trafarets))

    def check_and_return(self, value):
        errors = []
        for trafaret in self.trafarets:
            try:
                return trafaret.check(value)
            except DataError as e:
                errors.append(e)
        raise DataError(dict(enumerate(errors)))

    def __lshift__(self, trafaret):
        self.trafarets.append(self._trafaret(trafaret))
        return self

    def __or__(self, trafaret):
        self << trafaret
        return self

    def __repr__(self):
        return "<Or(%s)>" % (", ".join(map(repr, self.trafarets)))


class Null(Trafaret):

    """
    >>> Null()
    <Null>
    >>> Null().check(None)
    >>> extract_error(Null(), 1)
    'value should be None'
    """

    def check_value(self, value):
        if value is not None:
            self._failure("value should be None")

    def __repr__(self):
        return "<Null>"


class Bool(Trafaret):

    """
    >>> Bool()
    <Bool>
    >>> Bool().check(True)
    True
    >>> Bool().check(False)
    False
    >>> extract_error(Bool(), 1)
    'value 1 should be True or False'
    """

    def check_value(self, value):
        if not isinstance(value, bool):
            self._failure("value %s should be True or False" % value)

    def __repr__(self):
        return "<Bool>"


class StrBool(Trafaret):

    """
    >>> extract_error(StrBool(), 'aloha')
    "value aloha can't be converted to Bool"
    >>> StrBool().check(1)
    True
    >>> StrBool().check(0)
    False
    >>> StrBool().check('y')
    True
    >>> StrBool().check('n')
    False
    >>> StrBool().check(None)
    False
    >>> StrBool().check('1')
    True
    >>> StrBool().check('0')
    False
    >>> StrBool().check('YeS')
    True
    >>> StrBool().check('No')
    False
    >>> StrBool().check(True)
    True
    >>> StrBool().check(False)
    False
    """

    convertable = ('t', 'true', 'false', 'y', 'n', 'yes', 'no', 'on',
                   '1', '0', 'none')

    def _check(self, value):
        _value = str(value).strip().lower()
        if _value not in self.convertable:
            self._failure("value %s can't be converted to Bool" % value)

    def converter(self, value):
        if value is None:
            return False
        _str = str(value).strip().lower()

        return _str in ('t', 'true', 'y', 'yes', 'on', '1')

    def __repr__(self):
        return "<StrBool>"


class NumberMeta(TrafaretMeta):

    """
    Allows slicing syntax for min and max arguments for
    number trafarets

    >>> Int[1:]
    <Int(gte=1)>
    >>> Int[1:10]
    <Int(gte=1, lte=10)>
    >>> Int[:10]
    <Int(lte=10)>
    >>> Float[1:]
    <Float(gte=1)>
    >>> Int > 3
    <Int(gt=3)>
    >>> 1 < (Float < 10)
    <Float(gt=1, lt=10)>
    >>> (Int > 5).check(10)
    10
    >>> extract_error(Int > 5, 1)
    'value 1 should be greater than 5'
    >>> (Int < 3).check(1)
    1
    >>> extract_error(Int < 3, 3)
    'value 3 should be less than 3'
    """

    def __getitem__(cls, slice_):
        return cls(gte=slice_.start, lte=slice_.stop)

    def __lt__(cls, lt):
        return cls(lt=lt)

    def __gt__(cls, gt):
        return cls(gt=gt)


@py3metafix
class Float(Trafaret):

    """
    >>> Float()
    <Float>
    >>> Float(gte=1)
    <Float(gte=1)>
    >>> Float(lte=10)
    <Float(lte=10)>
    >>> Float(gte=1, lte=10)
    <Float(gte=1, lte=10)>
    >>> Float().check(1.0)
    1.0
    >>> extract_error(Float(), 1 + 3j)
    'value (1+3j) is not float'
    >>> extract_error(Float(), 1)
    1.0
    >>> Float(gte=2).check(3.0)
    3.0
    >>> extract_error(Float(gte=2), 1.0)
    'value 1.0 is less than 2'
    >>> Float(lte=10).check(5.0)
    5.0
    >>> extract_error(Float(lte=3), 5.0)
    'value 5.0 is greater than 3'
    >>> Float().check("5.0")
    5.0
    """

    __metaclass__ = NumberMeta

    convertable = str_types + (numbers.Real,)
    value_type = float

    def __init__(self, gte=None, lte=None, gt=None, lt=None):
        self.gte = gte
        self.lte = lte
        self.gt = gt
        self.lt = lt

    def _converter(self, val):
        if not isinstance(val, self.convertable):
            self._failure('value %s is not %s' % (val, self.value_type.__name__))
        try:
            return self.value_type(val)
        except ValueError:
            self._failure(
                "value %s can't be converted to %s" % (
                    val, self.value_type.__name__
                )
            )

    def check_and_return(self, val):
        if not isinstance(val, self.value_type):
            value = self._converter(val)
        else:
            value = val
        if self.gte is not None and value < self.gte:
            self._failure("value %s is less than %s" % (value, self.gte))
        if self.lte is not None and value > self.lte:
            self._failure("value %s is greater than %s" % (value, self.lte))
        if self.lt is not None and value >= self.lt:
            self._failure("value %s should be less than %s" % (value, self.lt))
        if self.gt is not None and value <= self.gt:
            self._failure("value %s should be greater than %s" % (value, self.gt))
        return value

    def __lt__(self, lt):
        return type(self)(gte=self.gte, lte=self.lte, gt=self.gt, lt=lt)

    def __gt__(self, gt):
        return type(self)(gte=self.gte, lte=self.lte, gt=gt, lt=self.lt)

    def __repr__(self):
        r = "<%s" % type(self).__name__
        options = []
        for param in ("gte", "lte", "gt", "lt"):
            if getattr(self, param) is not None:
                options.append("%s=%s" % (param, getattr(self, param)))
        if options:
            r += "(%s)" % (", ".join(options))
        r += ">"
        return r


class Int(Float):

    """
    >>> Int()
    <Int>
    >>> Int().check(5)
    5
    >>> extract_error(Int(), 1.1)
    'value 1.1 is not int'
    >>> extract_error(Int(), 1 + 1j)
    'value (1+1j) is not int'
    """

    value_type = int

    def _converter(self, val):
        if isinstance(val, float):
            if not val.is_integer():
                self._failure('value %s is not int' % (val))
        return super(Int, self)._converter(val)


class Atom(Trafaret):

    """
    >>> Atom('atom').check('atom')
    'atom'
    >>> extract_error(Atom('atom'), 'molecule')
    "value is not exactly 'atom'"
    """

    def __init__(self, value):
        self.value = value

    def check_value(self, value):
        if self.value != value:
            self._failure("value is not exactly '%s'" % self.value)


class String(Trafaret):

    """
    >>> String()
    <String>
    >>> String(allow_blank=True)
    <String(blank)>
    >>> String().check("foo")
    'foo'
    >>> extract_error(String(), "")
    'blank value is not allowed'
    >>> String(allow_blank=True).check("")
    ''
    >>> extract_error(String(), 1)
    'value is not a string'
    >>> String(regex='\w+').check('wqerwqer')
    'wqerwqer'
    >>> extract_error(String(regex='^\w+$'), 'wqe rwqer')
    "value 'wqe rwqer' does not match pattern: ^\\\w+$"
    >>> String(min_length=2, max_length=3).check('123')
    '123
    >>> extract_error(String(min_length=2, max_length=6), '1')'
    'String is shorter than 2 characters'
    >>> extract_error(String(min_length=2, max_length=6), '1234567')
    'String is longer than 6 characters'
    >>> String(min_length=2, max_length=6, allow_blank=True)
    Traceback (most recent call last):
    ...
    AssertionError: Either allow_blank or min_length should be specified, not both
    >>> String(min_length=0, max_length=6, allow_blank=True).check('123')
    '123'
    """

    def __init__(self, allow_blank=False, regex=None, min_length=None, max_length=None):
        assert not (allow_blank and min_length), \
            "Either allow_blank or min_length should be specified, not both"
        self.allow_blank = allow_blank
        self.regex = re.compile(regex) if isinstance(regex, str_types) else regex
        self.min_length = min_length
        self.max_length = max_length
        self._raw_regex = self.regex.pattern if self.regex else None

    def check_and_return(self, value):
        if not isinstance(value, str_types):
            self._failure("value is not a string")
        if not self.allow_blank and len(value) is 0:
            self._failure("blank value is not allowed")
        if self.min_length is not None and len(value) < self.min_length:
            self._failure('String is shorter than %s characters' % self.min_length)
        if self.max_length is not None and len(value) > self.max_length:
            self._failure('String is longer than %s characters' % self.max_length)
        if self.regex is not None:
            match = self.regex.match(value)
            if not match:
                self._failure("value '%s' does not match pattern: %s" % (
                    value, repr(self._raw_regex))
                )
            return match
        return value

    def converter(self, value):
        if isinstance(value, str_types):
            return value
        return value.group()

    def __repr__(self):
        return "<String(blank)>" if self.allow_blank else "<String>"


class Email(String):

    """
    >>> Email().check('someone@example.net')
    'someone@example.net'
    >>> extract_error(Email(),'someone@example') # try without domain-part
    'value is not a valid email address'
    >>> str(Email().check('someone@пример.рф')) # try with `idna` encoding
    'someone@xn--e1afmkfd.xn--p1ai'
    >>> (Email() >> (lambda m: m.groupdict()['domain'])).check('someone@example.net')
    'example.net'
    >>> extract_error(Email(),'foo')
    'value is not a valid email address'
    """

    regex = re.compile(
        r"(?P<name>^[-!#$%&'*+/=?^_`{}|~0-9A-Z]+(\.[-!#$%&'*+/=?^_`{}|~0-9A-Z]+)*"  # dot-atom
        r'|^"([\001-\010\013\014\016-\037!#-\[\]-\177]|\\[\001-011\013\014\016-\177])*"' # quoted-string
        r')@(?P<domain>(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)$)'  # domain
        r'|\[(25[0-5]|2[0-4]\d|[0-1]?\d?\d)(\.(25[0-5]|2[0-4]\d|[0-1]?\d?\d)){3}\]$', re.IGNORECASE)  # literal form, ipv4 address (SMTP 4.1.3)
    min_length = None
    max_length = None

    def __init__(self, allow_blank=False):
        super(Email, self).__init__(allow_blank=allow_blank, regex=self.regex)

    def check_and_return(self, value):
        try:
            return super(Email, self).check_and_return(value)
        except DataError:
            if value and isinstance(value, bytes):
                decoded = value.decode('utf-8')
            else:
                decoded = value
            # Trivial case failed. Try for possible IDN domain-part
            if decoded and '@' in decoded:
                parts = decoded.split('@')
                try:
                    parts[-1] = parts[-1].encode('idna').decode('ascii')
                except UnicodeError:
                    pass
                else:
                    try:
                        return super(Email, self).check_and_return('@'.join(parts))
                    except DataError:
                        # Will fail with main error
                        pass
        self._failure('value is not a valid email address')

    def __repr__(self):
        return '<Email>'


class URL(String):

    """
    >>> URL().check('http://example.net/resource/?param=value#anchor')
    'http://example.net/resource/?param=value#anchor'
    >>> str(URL().check('http://пример.рф/resource/?param=value#anchor'))
    'http://xn--e1afmkfd.xn--p1ai/resource/?param=value#anchor'
    """

    regex = re.compile(
        r'^(?:http|ftp)s?://' # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|' #domain...
        r'localhost|' #localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})' # ...or ip
        r'(?::\d+)?' # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    min_length = None
    max_length = None

    def __init__(self, allow_blank=False):
        super(URL, self).__init__(allow_blank=allow_blank, regex=self.regex)

    def check_and_return(self, value):
        try:
            return super(URL, self).check_and_return(value)
        except DataError:
            # Trivial case failed. Try for possible IDN domain-part
            if value:
                if isinstance(value, bytes):
                    decoded = value.decode('utf-8')
                else:
                    decoded = value
                scheme, netloc, path, query, fragment = urlparse.urlsplit(decoded)
                try:
                    netloc = netloc.encode('idna').decode('ascii') # IDN -> ACE
                except UnicodeError: # invalid domain part
                    pass
                else:
                    url = urlparse.urlunsplit((scheme, netloc, path, query, fragment))
                    return super(URL, self).check_and_return(url)
        self._failure('value is not URL')

    def __repr__(self):
        return '<URL>'


class SquareBracketsMeta(TrafaretMeta):

    """
    Allows usage of square brackets for List initialization

    >>> List[Int]
    <List(<Int>)>
    >>> List[Int, 1:]
    <List(min_length=1 | <Int>)>
    >>> List[:10, Int]
    <List(max_length=10 | <Int>)>
    >>> List[1:10]
    Traceback (most recent call last):
    ...
    RuntimeError: Trafaret is required for List initialization
    """

    def __getitem__(self, args):
        slice_ = None
        trafaret = None
        if not isinstance(args, tuple):
            args = (args, )
        for arg in args:
            if isinstance(arg, slice):
                slice_ = arg
            elif isinstance(arg, Trafaret) or issubclass(arg, Trafaret) \
                 or isinstance(arg, type):
                trafaret = arg
        if not trafaret:
            raise RuntimeError("Trafaret is required for List initialization")
        if slice_:
            return self(trafaret, min_length=slice_.start or 0,
                                  max_length=slice_.stop)
        return self(trafaret)


@py3metafix
class List(Trafaret):

    """
    >>> List(Int)
    <List(<Int>)>
    >>> List(Int, min_length=1)
    <List(min_length=1 | <Int>)>
    >>> List(Int, min_length=1, max_length=10)
    <List(min_length=1, max_length=10 | <Int>)>
    >>> extract_error(List(Int), 1)
    'value is not list'
    >>> List(Int).check([1, 2, 3])
    [1, 2, 3]
    >>> List(String).check(["foo", "bar", "spam"])
    ['foo', 'bar', 'spam']
    >>> extract_error(List(Int), [1, 2, 1 + 3j])
    {2: 'value (1+3j) is not int'}
    >>> List(Int, min_length=1).check([1, 2, 3])
    [1, 2, 3]
    >>> extract_error(List(Int, min_length=1), [])
    'list length is less than 1'
    >>> List(Int, max_length=2).check([1, 2])
    [1, 2]
    >>> extract_error(List(Int, max_length=2), [1, 2, 3])
    'list length is greater than 2'
    >>> extract_error(List(Int), ["a"])
    {0: "value a can't be converted to int"}
    """

    __metaclass__ = SquareBracketsMeta

    def __init__(self, trafaret, min_length=0, max_length=None):
        self.trafaret = self._trafaret(trafaret)
        self.min_length = min_length
        self.max_length = max_length

    def check_and_return(self, value):
        if not isinstance(value, list):
            self._failure("value is not list")
        if len(value) < self.min_length:
            self._failure("list length is less than %s" % self.min_length)
        if self.max_length is not None and len(value) > self.max_length:
            self._failure("list length is greater than %s" % self.max_length)
        lst = []
        errors = {}
        for index, item in enumerate(value):
            try:
                lst.append(self.trafaret.check(item))
            except DataError as err:
                errors[index] = err
        if errors:
            raise DataError(error=errors)
        return lst

    def __repr__(self):
        r = "<List("
        options = []
        if self.min_length:
            options.append("min_length=%s" % self.min_length)
        if self.max_length:
            options.append("max_length=%s" % self.max_length)
        r += ", ".join(options)
        if options:
            r += " | "
        r += repr(self.trafaret)
        r += ")>"
        return r


class Tuple(Trafaret):
    """
    Tuple checker can be used to check fixed tuples, like (Int, Int, String).

    >>> t = Tuple(Int, Int, String)
    >>> t.check([3, 4, '5'])
    (3, 4, '5')
    >>> extract_error(t, [3, 4, 5])
    {2: 'value is not a string'}
    >>> t
    <Tuple(<Int>, <Int>, <String>)
    """

    def __init__(self, *args):
        self.trafarets = list(map(self._trafaret, args))
        self.length = len(self.trafarets)

    def check_and_return(self, value):
        try:
            value = tuple(value)
        except TypeError:
            self._failure('value must be convertable to tuple')
        if len(value) != self.length:
            self._failure('value must contain exact %s items' % self.length)
        result = []
        errors = {}
        for idx, (item, trafaret) in enumerate(zip(value, self.trafarets)):
            try:
                result.append(trafaret.check(item))
            except DataError as err:
                errors[idx] = err
        if errors:
            self._failure(errors)
        return tuple(result)

    def __repr__(self):
        return '<Tuple(' + ', '.join(repr(t) for t in self.trafarets) + ')'


class Key(object):

    """
    Helper class for Dict.

    >>> default = lambda: 1
    >>> Key(name='test', default=default)
    <Key "test">
    >>> Key(name='test', default=default).pop({}).__next__()
    ('test', 1)
    >>> Key(name='test', default=2).pop({}).__next__()
    ('test', 2)
    >>> default = lambda: None
    >>> Key(name='test', default=default).pop({}).__next__()
    ('test', None)
    >>> Key(name='test', default=None).pop({}).__next__()
    ('test', None)
    >>> Key(name='test').pop({}).__next__()
    ('test', DataError(is required))
    >>> list(Key(name='test', optional=True).pop({}))
    []
    """

    def __init__(self, name, default=_empty, optional=False, to_name=None, trafaret=None):
        self.name = name
        self.to_name = to_name
        self.default = default
        self.optional = optional
        self.trafaret = trafaret or Any()

    def pop(self, data):
        if self.name in data or self.default is not _empty:
            if callable(self.default):
                default = self.default()
            else:
                default = self.default
            # default = callable(self.default) and self.default() or self.default
            yield self.get_name(), catch_error(self.trafaret,
                    data.pop(self.name, default))
            raise StopIteration

        if not self.optional:
            yield self.name, DataError(error='is required')

    def keys_names(self):
        yield self.name

    def set_trafaret(self, trafaret):
        self.trafaret = trafaret

    def __rshift__(self, name):
        self.to_name = name
        return self

    def get_name(self):
        return self.to_name or self.name

    def make_optional(self):
        self.optional = True

    def __repr__(self):
        return '<%s "%s"%s>' % (self.__class__.__name__, self.name,
           ' to "%s"' % self.to_name if getattr(self, 'to_name', False) else '')


class Dict(Trafaret):

    """
    >>> from reprlib import repr
    >>> trafaret = Dict(foo=Int, bar=String) >> ignore
    >>> trafaret.check({"foo": 1, "bar": "spam"})
    >>> extract_error(trafaret, {"foo": 1, "bar": 2})
    {'bar': 'value is not a string'}
    >>> extract_error(trafaret, {"foo": 1})
    {'bar': 'is required'}
    >>> extract_error(trafaret, {"foo": 1, "bar": "spam", "eggs": None})
    {'eggs': 'eggs is not allowed key'}
    >>> trafaret.allow_extra("eggs")
    <Dict(extras=(eggs) | bar=<String>, foo=<Int>)>
    >>> trafaret.check({"foo": 1, "bar": "spam", "eggs": None})
    >>> trafaret.check({"foo": 1, "bar": "spam"})
    >>> extract_error(trafaret, {"foo": 1, "bar": "spam", "ham": 100})
    {'ham': 'ham is not allowed key'}
    >>> trafaret.allow_extra("*")
    <Dict(any, extras=(eggs) | bar=<String>, foo=<Int>)>
    >>> trafaret.check({"foo": 1, "bar": "spam", "ham": 100})
    >>> trafaret.check({"foo": 1, "bar": "spam", "ham": 100, "baz": None})
    >>> extract_error(trafaret, {"foo": 1, "ham": 100, "baz": None})
    {'bar': 'is required'}
    >>> trafaret = Dict({Key('bar', optional=True): String}, foo=Int)
    >>> trafaret.allow_extra("*")
    <Dict(any | bar=<String>, foo=<Int>)>
    >>> trafaret.check({"foo": 1, "ham": 100, "baz": None})
    {'foo': 1, 'baz': None, 'ham': 100}
    >>> extract_error(trafaret, {"bar": 1, "ham": 100, "baz": None})
    {'foo': 'is required', 'bar': 'value is not string'}
    >>> extract_error(trafaret, {"foo": 1, "bar": 1, "ham": 100, "baz": None})
    {'bar': 'value is not a string'}
    >>> trafaret = Dict({Key('bar', default='nyanya') >> 'baz': String}, foo=Int)
    >>> repr(trafaret.check({'foo': 4}))
    "{'baz': 'nyanya', 'foo': 4}"
    >>> _ = trafaret.ignore_extra('fooz')
    >>> repr(trafaret.check({'foo': 4, 'fooz': 5}))
    "{'baz': 'nyanya', 'foo': 4}"
    >>> _ = trafaret.ignore_extra('*')
    >>> repr(trafaret.check({'foo': 4, 'foor': 5}))
    "{'baz': 'nyanya', 'foo': 4}"
    """

    def __init__(self, keys={}, **trafarets):
        self.extras = []
        self.allow_any = False
        self.ignore = []
        self.ignore_any = False
        self.keys = []
        for key, trafaret in itertools.chain(trafarets.items(), keys.items()):
            key_ = key if isinstance(key, Key) else Key(key)
            key_.set_trafaret(self._trafaret(trafaret))
            self.keys.append(key_)

    def allow_extra(self, *names):
        for name in names:
            if name == "*":
                self.allow_any = True
            else:
                self.extras.append(name)
        return self

    def ignore_extra(self, *names):
        for name in names:
            if name == "*":
                self.ignore_any = True
            else:
                self.ignore.append(name)
        return self

    def make_optional(self, *args):
        for key in self.keys:
            if key.name in args or '*' in args:
                key.make_optional()
        return self

    def check_and_return(self, value):
        if not isinstance(value, dict):
            self._failure("value '%s' is not dict" % value)
        data = copy.copy(value)
        collect = {}
        errors = {}
        for key in self.keys:
            for k, v in key.pop(data):
                if isinstance(v, DataError):
                    errors[k] = v
                else:
                    collect[k] = v
        if not self.ignore_any:
            for key in data:
                if key in self.ignore:
                    continue
                if not self.allow_any and key not in self.extras:
                    errors[key] = DataError("%s is not allowed key" % key)
                else:
                    collect[key] = data[key]
        if errors:
            raise DataError(error=errors)
        return collect

    def keys_names(self):
        for key in self.keys:
            for k in key.keys_names():
                yield k

    def __repr__(self):
        r = "<Dict("
        options = []
        if self.allow_any:
            options.append("any")
        if self.ignore:
            options.append("ignore=(%s)" % (", ".join(self.ignore)))
        if self.extras:
            options.append("extras=(%s)" % (", ".join(self.extras)))
        r += ", ".join(options)
        if options:
            r += " | "
        options = []
        for key in sorted(self.keys, key=lambda k: k.name):
            options.append("%s=%r" % (key.name, key.trafaret))
        r += ", ".join(options)
        r += ")>"
        return r


def DictKeys(keys):
    """
    Checks if dict has all given keys

    :param keys:
    :type keys:

    >>> DictKeys(['a','b']).check({'a':1,'b':2,})
    {'a': 1, 'b': 2}
    >>> extract_error(DictKeys(['a','b']), {'a':1,'b':2,'c':3,})
    {'c': 'c is not allowed key'}
    >>> extract_error(DictKeys(['key','key2']), {'key':'val'})
    {'key2': 'is required'}
    """
    def MissingKey(val):
        raise DataError('%s is not in Dict' % val)

    req = [(Key(key), Any) for key in keys]
    return Dict(dict(req))


class Mapping(Trafaret):

    r"""
    >>> from reprlib import repr
    >>> trafaret = Mapping(String, Int)
    >>> trafaret
    <Mapping(<String> => <Int>)>
    >>> repr(trafaret.check({"foo": 1, "bar": 2}))
    "{'bar': 2, 'foo': 1}"
    >>> extract_error(trafaret, {"foo": 1, "bar": None})
    {'bar': {'value': 'value None is not int'}}
    >>> extract_error(trafaret, {"foo": 1, 2: "bar"})
    {2: {'key': 'value is not string', 'value': "value bar can't be converted to int"}}
    """

    def __init__(self, key, value):
        self.key = self._trafaret(key)
        self.value = self._trafaret(value)

    def check_and_return(self, mapping):
        checked_mapping = {}
        errors = {}
        for key, value in mapping.items():
            pair_errors = {}
            try:
                checked_key = self.key.check(key)
            except DataError as err:
                pair_errors['key'] = err
            try:
                checked_value = self.value.check(value)
            except DataError as err:
                pair_errors['value'] = err
            if pair_errors:
                errors[key] = DataError(error=pair_errors)
            else:
                checked_mapping[checked_key] = checked_value
        if errors:
            raise DataError(error=errors)
        return checked_mapping

    def __repr__(self):
        return "<Mapping(%r => %r)>" % (self.key, self.value)


class Enum(Trafaret):

    """
    >>> trafaret = Enum("foo", "bar", 1) >> ignore
    >>> trafaret
    <Enum('foo', 'bar', 1)>
    >>> trafaret.check("foo")
    >>> trafaret.check(1)
    >>> extract_error(trafaret, 2)
    "value doesn't match any variant"
    """

    def __init__(self, *variants):
        self.variants = variants[:]

    def check_value(self, value):
        if value not in self.variants:
            self._failure("value doesn't match any variant")

    def __repr__(self):
        return "<Enum(%s)>" % (", ".join(map(repr, self.variants)))


class Callable(Trafaret):

    """
    >>> (Callable() >> ignore).check(lambda: 1)
    >>> extract_error(Callable(), 1)
    'value is not callable'
    """

    def check_value(self, value):
        if not callable(value):
            self._failure("value is not callable")

    def __repr__(self):
        return "<Callable>"


class Call(Trafaret):

    """
    >>> def validator(value):
    ...     if value != "foo":
    ...         return DataError("I want only foo!")
    ...     return 'foo'
    ...
    >>> trafaret = Call(validator)
    >>> trafaret
    <Call(validator)>
    >>> trafaret.check("foo")
    'foo'
    >>> extract_error(trafaret, "bar")
    'I want only foo!'
    """

    def __init__(self, fn):
        if not callable(fn):
            raise RuntimeError("Call argument should be callable")
        argspec = inspect.getargspec(fn)
        if len(argspec.args) - len(argspec.defaults or []) > 1:
            raise RuntimeError("Call argument should be"
                               " one argument function")
        self.fn = fn

    def check_and_return(self, value):
        res = self.fn(value)
        if isinstance(res, DataError):
            raise res
        else:
            return res

    def __repr__(self):
        return "<Call(%s)>" % self.fn.__name__


class Forward(Trafaret):

    """
    >>> node = Forward()
    >>> node << Dict(name=String, children=List[node])
    >>> node
    <Forward(<Dict(children=<List(<recur>)>, name=<String>)>)>
    >>> node.check({"name": "foo", "children": []}) == {'children': [], 'name': 'foo'}
    True
    >>> extract_error(node, {"name": "foo", "children": [1]})
    {'children': {0: "value '1' is not dict"}}
    >>> node.check({"name": "foo", "children": [ \
                        {"name": "bar", "children": []} \
                     ]}) == {'children': [{'children': [], 'name': 'bar'}], 'name': 'foo'}
    True
    >>> empty_node = Forward()
    >>> empty_node
    <Forward(None)>
    >>> extract_error(empty_node, 'something')
    'trafaret not set yet'
    """

    def __init__(self):
        self.trafaret = None
        self._recur_repr = False

    def __lshift__(self, trafaret):
        self.provide(trafaret)

    def provide(self, trafaret):
        if self.trafaret:
            raise RuntimeError("trafaret for Forward is already specified")
        self.trafaret = self._trafaret(trafaret)

    def check_and_return(self, value):
        if self.trafaret is None:
            self._failure('trafaret not set yet')
        return self.trafaret.check(value)

    def __repr__(self):
        # XXX not threadsafe
        if self._recur_repr:
            return "<recur>"
        self._recur_repr = True
        r = "<Forward(%r)>" % self.trafaret
        self._recur_repr = False
        return r


class GuardError(DataError):

    """
    Raised when guarded function gets invalid arguments,
    inherits error message from corresponding DataError
    """

    pass


def guard(trafaret=None, **kwargs):
    """
    Decorator for protecting function with trafarets

    >>> @guard(a=String, b=Int, c=String)
    ... def fn(a, b, c="default"):
    ...     '''docstring'''
    ...     return (a, b, c)
    ...
    >>> fn.__module__ = None
    >>> help(fn)
    Help on function fn:
    <BLANKLINE>
    fn(*args, **kwargs)
        guarded with <Dict(a=<String>, b=<Int>, c=<String>)>
    <BLANKLINE>
        docstring
    <BLANKLINE>
    >>> fn("foo", 1)
    ('foo', 1, 'default')
    >>> extract_error(fn, "foo", 1, 2)
    {'c': 'value is not a string'}
    >>> extract_error(fn, "foo")
    {'b': 'is required'}
    >>> g = guard(Dict())
    >>> c = Forward()
    >>> c << Dict(name=str, children=List[c])
    >>> g = guard(c)
    >>> g = guard(Int())
    Traceback (most recent call last):
    ...
    RuntimeError: trafaret should be instance of Dict or Forward
    """
    if trafaret and not isinstance(trafaret, Dict) and \
                    not isinstance(trafaret, Forward):
        raise RuntimeError("trafaret should be instance of Dict or Forward")
    elif trafaret and kwargs:
        raise RuntimeError("choose one way of initialization,"
                           " trafaret or kwargs")
    if not trafaret:
        trafaret = Dict(**kwargs)

    def wrapper(fn):
        argspec = inspect.getargspec(fn)

        @functools.wraps(fn)
        def decor(*args, **kwargs):
            fnargs = argspec.args
            if fnargs[0] in ['self', 'cls']:
                fnargs = fnargs[1:]
                checkargs = args[1:]
            else:
                checkargs = args

            try:
                call_args = dict(
                    itertools.chain(zip(fnargs, checkargs), kwargs.items())
                )
                for name, default in zip(reversed(fnargs),
                                         argspec.defaults or ()):
                    if name not in call_args:
                        call_args[name] = default
                converted = trafaret.check(call_args)
            except DataError as err:
                raise GuardError(error=err.error)
            return fn(**converted)
        decor.__doc__ = "guarded with %r\n\n" % trafaret + (decor.__doc__ or "")
        return decor
    return wrapper


def ignore(val):
    """
    Stub to ignore value from trafaret
    Use it like:

    >>> a = Int >> ignore
    >>> a.check(7)
    """
    pass


def catch_error(checker, *a, **kw):

    """
    Helper for tests - catch error and return it as dict
    """

    try:
        if hasattr(checker, 'check'):
            return checker.check(*a, **kw)
        elif callable(checker):
            return checker(*a, **kw)
    except DataError as error:
        return error


def extract_error(checker, *a, **kw):

    """
    Helper for tests - catch error and return it as dict
    """

    res = catch_error(checker, *a, **kw)
    if isinstance(res, DataError):
        return res.as_dict()
    return res


def load_contrib():
    for entrypoint in pkg_resources.iter_entry_points(ENTRY_POINT):
        try:
            trafaret_class = entrypoint.load()
            setattr(sys.modules[__name__], trafaret_class.__name__,
                    trafaret_class)
        except pkg_resources.DistributionNotFound as err:
            # TODO: find a way to pass error message upper
            pass
load_contrib()
