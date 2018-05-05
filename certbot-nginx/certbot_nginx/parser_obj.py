"""NginxParser is a member object of the NginxConfigurator class."""
import abc
import copy
import itertools
import glob
import logging
import os
import pyparsing
import six

from certbot import errors

from certbot_nginx import nginxparser
from certbot_nginx import obj

logger = logging.getLogger(__name__)

# TODO (sydli) : Flesh out docstrings
REPEATABLE_DIRECTIVES = set(['server_name', 'listen', 'include', 'rewrite'])
COMMENT = ' managed by Certbot'
COMMENT_BLOCK = ['#', COMMENT]

def is_certbot_comment(parsed_obj):
    """ Checks whether parsed_obj is a certbot comment.
    """
    if not isinstance(parsed_obj, Sentence):
        return False
    for item in COMMENT_BLOCK:
        if item not in parsed_obj.words:
            return False
    return True

class WithLists(object):
    """ Abstract base class for "Parsable" objects whose underlying representation
    is a tree of lists. """

    __metaclass__ = abc.ABCMeta

    def __init__(self, context):
        self._data = []
        self._tabs = None
        self.context = context

    @abc.abstractmethod
    def parse(self, raw_list, add_spaces=False):
        """ Loads information into this object from underlying raw_list structure.
        Each Parsable object might make different assumptions about the structure of
        raw_list. """
        raise NotImplementedError()

    def child_context(self, filename=None):
        """ Spans a child context (with this object as the parent)
        """
        if self.context is None:
            return None
        if filename is None:
            filename = self.context.filename
        return ParseContext(self.context.cwd, filename, self, self.context.parsed_files,
                            self.context.parsing_hooks)

    @abc.abstractmethod
    def get_tabs(self):
        """ Guess at the number of preceding whitespaces """
        raise NotImplementedError()

    def dump(self, include_spaces=False):
        """ Retrieves readable underlying representaiton. setting include_spaces
        to False is equivalent to the old UnspacedList object. """
        return [elem.dump(include_spaces) for elem in self._data]

# parsing hook things

def _is_bloc(list_):
    return isinstance(list_, list) and len(list_) == 2 and isinstance(list_[1], list)

def _is_sentence(list_):
    return isinstance(list_, list) and all([isinstance(elem, six.string_types) for elem in list_])

def _choose_parser(child_context, list_):
    for hook, type_ in child_context.parsing_hooks:
        if hook(list_):
            return type_(child_context)
    raise errors.MisconfigurationError(
        "None of the parsing hooks succeeded, so we don't know how to parse this set of lists.")

# important functions

def parse_raw(lists_, context, add_spaces=False):
    """ TODO
    """
    parser = _choose_parser(context, lists_)
    parser.parse(lists_, add_spaces)
    return parser

def parse_raw_nginx(lists_, context=None):
    """ TODO
    """
    if context is None:
        return parse_raw(lists_, NginxParseContext())
    return parse_raw(lists_, context)

class Statements(WithLists):
    """ A group or list of "Statements". A Statement is either a Block or a Directive.
    """
    def __init__(self, context=None):
        super(Statements, self).__init__(context)
        self._trailing_whitespace = None

    def set_tabs(self, tabs='    '):
        """ TODO
        """
        for statement in self._data:
            statement.set_tabs(tabs)
        self._trailing_whitespace = '\n' + self.context.parent.get_tabs()

    def parse(self, parse_this, add_spaces=False):
        """ Assumes parse_this is a list of parseable lists. """
        if not isinstance(parse_this, list):
            raise errors.MisconfigurationError("Statements parsing expects a list!")
        # If there's a trailing whitespace in the list of statements, keep track of it.
        if len(parse_this) > 0 and isinstance(parse_this[-1], six.string_types) \
                               and parse_this[-1].isspace():
            self._trailing_whitespace = parse_this[-1]
            parse_this = parse_this[:-1]
        self._data = [parse_raw(elem, self.child_context(), add_spaces) for elem in parse_this]

    def get_tabs(self):
        """ Takes a guess at the tabbing of all contained Statements-- by retrieving the
        tabbing of the first Statement."""
        if len(self._data) > 0:
            return self._data[0].get_tabs()
        return ''

    def dump(self, include_spaces=False):
        """ TODO """
        data = super(Statements, self).dump(include_spaces)
        if include_spaces and self._trailing_whitespace is not None:
            return data + [self._trailing_whitespace]
        return data

    def iterate_expanded(self):
        """ Generator for Statements-- and expands includes automatically.  """
        for elem in self._data:
            if isinstance(elem, Include):
                for parsed in elem.parsed.values():
                    for sub_elem in parsed.iterate_expanded():
                        yield sub_elem
            yield elem

    def _get_thing(self, match_func):
        for elem in self.iterate_expanded():
            if match_func(elem):
                yield elem

    def get_thing_shallow(self, match_func):
        """ Retrieves any Statement that returns true for match_func--
        Not recursive (so does not recurse on nested Blocs). """
        for elem in self._data:
            if match_func(elem):
                yield elem

    def get_type(self, match_type, match_func=None):
        """ Retrieve objects of a particluar type """
        return self._get_thing(lambda elem: isinstance(elem, match_type) and  \
                                   (match_func is None or match_func(elem)))

    def get_thing_recursive(self, match_func):
        """ Retrieves anything in the tree that returns true for match_func,
        also expands includes. """
        results = self._get_thing(match_func)
        for bloc in self.get_type(Bloc):
            results = itertools.chain(results, bloc.contents.get_thing_recursive(match_func))
        return results

    def get_directives(self, name):
        """ Retrieves any directive starting with |name|. Expands includes."""
        return self.get_type(Sentence, lambda sentence: sentence[0] == name)

    def _get_statement_index(self, match_func):
        """ Retrieves index of first occurrence of |directive| """
        for i, elem in enumerate(self._data):
            if isinstance(elem, Sentence) and match_func(elem):
                return i
        return -1

    def contains_exact_directive(self, statement):
        """ Returns true if |statement| is in this list of statements (+ expands includes)"""
        for elem in self.iterate_expanded():
            if isinstance(elem, Sentence) and elem.matches_list(statement):
                return True
        return False

    def replace_statement(self, statement, match_func, insert_at_top=False):
        """ For each statement, checks to see if an exisitng directive of that name
        exists. If so, replace the first occurrence with the statement. Otherwise, just
        add it to this object. """
        found = self._get_statement_index(match_func)
        if found < 0:
            # TODO (sydli): this level of abstraction shouldn't know about certbot_comments.
            self.add_statement(statement, insert_at_top)
            return
        statement = parse_raw(statement, self.child_context(), add_spaces=True)
        statement.set_tabs(self.get_tabs())
        self._data[found] = statement
        if found + 1 >= len(self._data) or not is_certbot_comment(self._data[found+1]):
            self._data.insert(found+1, certbot_comment(self.context))
        # TODO (sydli): if there's no comment here already, add a comment

    def add_statement(self, statement, insert_at_top=False):
        """ Adds a Statement to the end of this block of statements. """
        statement = parse_raw(statement, self.child_context(), add_spaces=True)
        statement.set_tabs(self.get_tabs())
        index = 0
        if insert_at_top:
            self._data.insert(0, statement)
        else:
            index = len(self._data)
            self._data.append(statement)
        if not isinstance(statement, Sentence) or not statement.is_comment():
            self._data.insert(index+1, certbot_comment(self.context))
        return statement

    def remove_statements(self, match_func):
        """ Removes statements from this object."""
        found = self._get_statement_index(match_func)
        while found >= 0:
            del self._data[found]
            if found < len(self._data) and is_certbot_comment(self._data[found]):
                del self._data[found]
            found = self._get_statement_index(match_func)

    @staticmethod
    def load_from(context):
        """ Creates a Statements object from the file referred to by context.
        """
        raw_parsed = []
        with open(os.path.join(context.cwd, context.filename)) as _file:
            try:
                raw_parsed = nginxparser.load_raw(_file)
            except pyparsing.ParseException as err:
                logger.debug("Could not parse file: %s due to %s", context.filename, err)
        statements = Statements(context)
        statements.parse(raw_parsed)
        context.parsed_files[context.filename] = statements
        return statements

def certbot_comment(context, preceding_spaces=4):
    """ A "Managed by Certbot" comment :) """
    result = Sentence(context)
    result.parse([' ' * preceding_spaces] + COMMENT_BLOCK)
    return result

def spaces_after_newline(word):
    """ Retrieves number of spaces after final newline in word."""
    if not word.isspace():
        return ''
    rindex = word.rfind('\n') # TODO: check \r
    return word[rindex+1:]

class Sentence(WithLists):
    """ A list of words. Non-whitespace words are  typically separated with some
    amount of whitespace. """
    def parse(self, parse_this, add_spaces=False):
        """ Expects a list of strings.  """
        if add_spaces:
            parse_this = _space_list(parse_this)
        if not isinstance(parse_this, list):
            raise errors.MisconfigurationError("Sentence parsing expects a list!")
        self._data = parse_this

    def set_tabs(self, tabs='    '):
        """ TODO """
        self._data.insert(0, '\n' + tabs)

    def is_comment(self):
        """ Is this sentence a comment? """
        if len(self.words) == 0:
            return False
        return self.words[0] == '#'

    @property
    def words(self):
        """ Iterates over words, but without spaces. Like Unspaced List. """
        return [word.strip('"\'') for word in self._data if not word.isspace()]

    def matches_list(self, list_):
        """ Checks to see whether this object matches an unspaced list. """
        for i, word in enumerate(self.words):
            if word == '#' and i == len(list_):
                return True
            if word != list_[i]:
                return False
        return True

    def __getitem__(self, index):
        return self.words[index]

    def dump(self, include_spaces=False):
        """ TODO """
        if not include_spaces:
            return self.words
        return self._data

    def get_tabs(self):
        """ TODO """
        return spaces_after_newline(self._data[0])

class Include(Sentence):
    """ An include statement. """
    def __init__(self, context=None):
        super(Include, self).__init__(context)
        self.parsed = None

    def parse(self, parse_this, add_spaces=False):
        """ Parsing an include touches disk-- this will fetch the associated
        files and actually parse them all! """
        super(Include, self).parse(parse_this, add_spaces)
        files = glob.glob(os.path.join(self.context.cwd, self.filename))
        self.parsed = {}
        for f in files:
            if f in self.context.parsed_files:
                self.parsed[f] = self.context.parsed_files[f]
            else:
                self.parsed[f] = Statements.load_from(self.child_context(f))

    @property
    def filename(self):
        """ Retrieves the filename that is being included. """
        return self.words[1]

def _space_list(list_):
    spaced_statement = []
    for i in reversed(six.moves.xrange(len(list_))):
        spaced_statement.insert(0, list_[i])
        if i > 0 and not list_[i].isspace() and not list_[i-1].isspace():
            spaced_statement.insert(0, ' ')
    return spaced_statement

class Bloc(WithLists):
    """ Any sort of bloc, denoted by a block name and curly braces. """
    def __init__(self, context=None):
        super(Bloc, self).__init__(context)
        self.names = None
        self.contents = None

    def set_tabs(self, tabs='    '):
        """ TODO
        """
        self.names.set_tabs(tabs)
        self.contents.set_tabs(tabs + '    ')

    def parse(self, parse_this, add_spaces=False):
        """ Expects a list of two! """
        if not isinstance(parse_this, list) or len(parse_this) != 2:
            raise errors.MisconfigurationError("Bloc parsing expects a list of length 2!")
         #if add_spaces:
         #    parse_this = _space_list(parse_this, self.parent.get_tabs())
        self.names = Sentence(self.child_context())
        if add_spaces:
            parse_this[0].append(' ')
        self.names.parse(parse_this[0], add_spaces)
        self.contents = Statements(self.child_context())
        self.contents.parse(parse_this[1], add_spaces)
        self._data = [self.names, self.contents]

    def get_tabs(self):
        return self.names.get_tabs()

class ServerBloc(Bloc):
    """ This bloc should parallel a vhost! """

    def __init__(self, context=None):
        super(ServerBloc, self).__init__(context)
        self.addrs = set()
        self.ssl = False
        self.server_names = set()
        self.vhost = None

    def _update_vhost(self):
        self.addrs = set()
        self.ssl = False
        self.server_names = set()
        for listen in self.contents.get_directives('listen'):
            addr = obj.Addr.fromstring(" ".join(listen[1:]))
            if addr:
                self.addrs.add(addr)
                if addr.ssl:
                    self.ssl = True
        for name in self.contents.get_directives('server_name'):
            self.server_names.update(name[1:])
        for ssl in self.contents.get_directives('ssl'):
            if ssl.words[1] == 'on':
                self.ssl = True

        self.vhost.addrs = self.addrs
        self.vhost.names = self.server_names
        self.vhost.ssl = self.ssl
        self.vhost.raw = self

    # TODO (sydli): contextual sentences/blocks should be parsed automatically
    # (get rid of `is_block`)
    def _add_directive(self, statement, insert_at_top=False, is_block=False):
        # pylint: disable=protected-access
        # ensure no duplicates
        if self.contents.contains_exact_directive(statement):
            return
        # ensure, if it's not repeatable, that it's not repeated
        if not is_block and statement[0] not in REPEATABLE_DIRECTIVES and len(
            list(self.contents.get_directives(statement[0]))) > 0:
            raise errors.MisconfigurationError(
                "Existing %s directive conflicts with %s", statement[0], statement)
        self.contents.add_statement(statement, insert_at_top)

    def add_directives(self, statements, insert_at_top=False, is_block=False):
        """ Add statements to this object. If the exact statement already exists,
        don't add it.

        doesn't expect spaces between elements in statements """
        if is_block:
            self._add_directive(statements, insert_at_top, is_block)
        else:
            for statement in statements:
                self._add_directive(statement, insert_at_top, is_block)
        self._update_vhost()

    def replace_directives(self, statements, insert_at_top=False):
        """ Adds statements to this object. For each of the statements,
        if one of this statement type already exists, replaces existing statement.
        """
        for s in statements:
            self.contents.replace_statement(s, lambda x, s=s: x[0] == s[0], insert_at_top)
        self._update_vhost()

    def remove_directives(self, directive, match_func=None):
        """ Removes statements from this object."""
        self.contents.remove_statements(lambda x: x[0] == directive and \
            (match_func is None or match_func(x)))
        self._update_vhost()

    def parse(self, parse_this, add_spaces=False):
        super(ServerBloc, self).parse(parse_this, add_spaces)
        self.vhost = obj.VirtualHost(self.context.filename if self.context is not None else "",
            self.addrs, self.ssl, True, self.server_names, self, None)
        self._update_vhost()


    def duplicate(self, only_directives=None, remove_singleton_listen_params=False):
        """ Duplicates iteslf into another sibling server block. """
        # pylint: disable=protected-access
        dup_bloc = self.context.parent.add_statement(copy.deepcopy(self.dump()))
        if only_directives is not None:
            dup_bloc.contents.remove_statements(lambda x: x[0] not in only_directives)
        if remove_singleton_listen_params:
            for directive in dup_bloc.contents.get_directives('listen'):
                for word in ['default_server', 'default', 'ipv6only=on']:
                    if word in directive.words:
                        directive._data.remove(word)
        dup_bloc.context.parent = self.context.parent
        dup_bloc._update_vhost()
        return dup_bloc

DEFAULT_PARSING_HOOKS = (
    (_is_bloc, Bloc),
    (_is_sentence, Sentence),
    (lambda list_: isinstance(list_, list), Statements)
)

class ParseContext(object):
    """ Context information held by parsed objects. """
    def __init__(self, cwd, filename, parent=None, parsed_files=None,
                 parsing_hooks=DEFAULT_PARSING_HOOKS):
        self.parsing_hooks = parsing_hooks
        self.cwd = cwd
        self.filename = filename
        self.parent = parent
        # We still need a global parsed files map so only one reference exists
        # to each individual file's parsed tree, even when expanding includes.
        if parsed_files is None:
            parsed_files = {}
        self.parsed_files = parsed_files


NGINX_PARSING_HOOKS = (
    (lambda list_: _is_bloc(list_) and 'server' in list_[0], ServerBloc),
    (lambda list_: _is_sentence(list_) and 'include' in list_, Include),
) + DEFAULT_PARSING_HOOKS

class NginxParseContext(ParseContext):
    """ TODO
    """
    def __init__(self, cwd="", filename="", parent=None, parsed_files=None,
                 parsing_hooks=NGINX_PARSING_HOOKS):
        super(NginxParseContext, self).__init__(cwd, filename, parent, parsed_files,
            parsing_hooks)
