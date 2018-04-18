"""Tests for certbot_nginx.parser."""
import glob
import os
import re
import shutil
import unittest
import filecmp

from certbot import errors

from certbot_nginx import nginxparser
from certbot_nginx import obj
from certbot_nginx import better_parser
from certbot_nginx.tests import util


class NginxFancyParserTest(util.NginxTest): #pylint: disable=too-many-public-methods
    """Nginx Parser Test."""

    def setUp(self):
        super(NginxFancyParserTest, self).setUp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)
        shutil.rmtree(self.config_dir)
        shutil.rmtree(self.work_dir)

    def test_root_normalized(self):
        path = os.path.join(self.temp_dir, "etc_nginx/////"
                            "ubuntu_nginx/../../etc_nginx")
        nparser = better_parser.FancyNginxParser(path)
        self.assertEqual(nparser.root, self.config_path)

    def test_root_absolute(self):
        nparser = better_parser.FancyNginxParser(os.path.relpath(self.config_path))
        self.assertEqual(nparser.root, self.config_path)

    def test_root_no_trailing_slash(self):
        nparser = better_parser.FancyNginxParser(self.config_path + os.path.sep)
        self.assertEqual(nparser.root, self.config_path)

    def test_basic(self):
        nparser = better_parser.FancyNginxParser(self.config_path)
        nparser.load()

    def test_load(self):
        """Test recursive conf file parsing.

        """
        nparser = better_parser.FancyNginxParser(self.config_path)
        nparser.load()
        self.assertEqual(set([nparser.abs_path(x) for x in
                              ['foo.conf', 'nginx.conf', 'server.conf', 'mime.types',
                               'sites-enabled/default',
                               'sites-enabled/example.com',
                               'sites-enabled/migration.com',
                               'sites-enabled/sslon.com',
                               'sites-enabled/globalssl.com',
                               'sites-enabled/ipv6.com',
                               'sites-enabled/ipv6ssl.com']]),
                         set(nparser.parsed.keys()))
        self.assertEqual([['server_name', 'somename', 'alias', 'another.alias']],
                         nparser.parsed[nparser.abs_path('server.conf')].get_data())
        self.assertEqual([[['server'], [['listen', '69.50.225.155:9000'],
                                        ['listen', '127.0.0.1'],
                                        ['server_name', '.example.com'],
                                        ['server_name', 'example.*']]]],
                         nparser.parsed[nparser.abs_path(
                             'sites-enabled/example.com')].get_data())

    def test_abs_path(self):
        nparser = better_parser.FancyNginxParser(self.config_path)
        self.assertEqual('/etc/nginx/*', nparser.abs_path('/etc/nginx/*'))
        self.assertEqual(os.path.join(self.config_path, 'foo/bar/'),
                         nparser.abs_path('foo/bar/'))

    def test_filedump(self):
        nparser = better_parser.FancyNginxParser(self.config_path)
        nparser.filedump('test', lazy=False)
        all_files =  glob.glob(nparser.abs_path('sites-enabled/*.test'))
        for f in all_files:
            if '.test' not in f:
                self.assertTrue(filecmp.cmp(
                    nparser.abs_path(f + '.test'),
                    nparser.abs_path(f)))
        parsed = better_parser.RootStatements(self.config_path, nparser.abs_path(
            'sites-enabled/example.com.test'))
        self.assertEqual([[['server'], [['listen', '69.50.225.155:9000'],
                                        ['listen', '127.0.0.1'],
                                        ['server_name', '.example.com'],
                                        ['server_name', 'example.*']]]],
                         parsed.get_data())

    def test_filedump_whitespace(self):
        nparser = better_parser.FancyNginxParser(self.config_path, 'funky_whitespace.conf')
        nparser.filedump('test', lazy=False)
        f = 'funky_whitespace.conf'
        self.assertTrue(filecmp.cmp(
            nparser.abs_path(f + '.test'),
            nparser.abs_path(f)))

    def test_get_vhosts_global_ssl(self):
        nparser = better_parser.FancyNginxParser(self.config_path)
        vhosts = nparser.get_vhosts()

        vhost = obj.VirtualHost(nparser.abs_path('sites-enabled/globalssl.com'),
                                [obj.Addr('4.8.2.6', '57', True, False,
                                          False, False)],
                                True, True, set(['globalssl.com']), [], None)

        globalssl_com = [x for x in vhosts if 'globalssl.com' in x.filep][0]
        self.assertEqual(vhost, globalssl_com)

    def test_get_vhosts(self):
        nparser = better_parser.FancyNginxParser(self.config_path)
        vhosts = nparser.get_vhosts()

        vhost1 = obj.VirtualHost(nparser.abs_path('nginx.conf'),
                                 [obj.Addr('', '8080', False, False,
                                           False, False)],
                                 False, True,
                                 set(['localhost',
                                      r'~^(www\.)?(example|bar)\.']),
                                 [], None)
        vhost2 = obj.VirtualHost(nparser.abs_path('nginx.conf'),
                                 [obj.Addr('somename', '8080', False, False,
                                           False, False),
                                  obj.Addr('', '8000', False, False,
                                           False, False)],
                                 False, True,
                                 set(['somename', 'another.alias', 'alias']),
                                 [], None)
        vhost3 = obj.VirtualHost(nparser.abs_path('sites-enabled/example.com'),
                                 [obj.Addr('69.50.225.155', '9000',
                                           False, False, False, False),
                                  obj.Addr('127.0.0.1', '', False, False,
                                           False, False)],
                                 False, True,
                                 set(['.example.com', 'example.*']), [], None)
        vhost4 = obj.VirtualHost(nparser.abs_path('sites-enabled/default'),
                                 [obj.Addr('myhost', '', False, True,
                                           False, False),
                                  obj.Addr('otherhost', '', False, True,
                                           False, False)],
                                 False, True, set(['www.example.org']),
                                 [], None)
        vhost5 = obj.VirtualHost(nparser.abs_path('foo.conf'),
                                 [obj.Addr('*', '80', True, True,
                                           False, False)],
                                 True, True, set(['*.www.foo.com',
                                                  '*.www.example.com']),
                                 [], None)

        self.assertEqual(12, len(vhosts))
        example_com = [x for x in vhosts if 'example.com' in x.filep][0]
        self.assertEqual(vhost3, example_com)
        default = [x for x in vhosts if 'default' in x.filep][0]
        self.assertEqual(vhost4, default)
        fooconf = [x for x in vhosts if 'foo.conf' in x.filep][0]
        self.assertEqual(vhost5, fooconf)
        localhost = [x for x in vhosts if 'localhost' in x.names][0]
        self.assertEqual(vhost1, localhost)
        somename = [x for x in vhosts if 'somename' in x.names][0]
        self.assertEqual(vhost2, somename)

    def test_has_ssl_on_directive(self):
        nparser = better_parser.FancyNginxParser(self.config_path)
        mock_vhost = obj.VirtualHost(None, None, None, None, None,
            better_parser.ServerBloc([['server', 'something'], 
              [['listen', 'myhost default_server'],
               ['server_name', 'www.example.org'],
               [['location', '/'], [['root', 'html'], ['index', 'index.html index.htm']]]
               ]], None), None)
        self.assertFalse(nparser.has_ssl_on_directive(mock_vhost))
        mock_vhost.raw = better_parser.ServerBloc([['server', 'something'], [
                          ['listen', '*:80', 'default_server', 'ssl'],
                          ['server_name', '*.www.foo.com', '*.www.example.com'],
                          ['root', '/home/ubuntu/sites/foo/']]], None)
        self.assertFalse(nparser.has_ssl_on_directive(mock_vhost))
        mock_vhost.raw = better_parser.ServerBloc([['server', 'something'], [
                          ['listen', '80 ssl'],
                          ['server_name', '*.www.foo.com', '*.www.example.com']]], None)
        self.assertFalse(nparser.has_ssl_on_directive(mock_vhost))
        mock_vhost.raw = better_parser.ServerBloc([['server','something'], [
                          ['listen', '80'],
                          ['ssl', 'on'],
                          ['server_name', '*.www.foo.com', '*.www.example.com']]], None)
        self.assertTrue(nparser.has_ssl_on_directive(mock_vhost))


#     def test_remove_server_directives(self):
#         nparser = parser.NginxParser(self.config_path)
#         mock_vhost = obj.VirtualHost(nparser.abs_path('nginx.conf'),
#                                      None, None, None,
#                                      set(['localhost',
#                                            r'~^(www\.)?(example|bar)\.']),
#                                      None, [10, 1, 9])
#         example_com = nparser.abs_path('sites-enabled/example.com')
#         names = set(['.example.com', 'example.*'])
#         mock_vhost.filep = example_com
#         mock_vhost.names = names
#         mock_vhost.path = [0]
#         nparser.add_server_directives(mock_vhost,
#                                       [['foo', 'bar'], ['ssl_certificate',
#                                                         '/etc/ssl/cert2.pem']],
#                                       replace=False)
#         nparser.remove_server_directives(mock_vhost, 'foo')
#         nparser.remove_server_directives(mock_vhost, 'ssl_certificate')
#         self.assertEqual(nparser.parsed[example_com],
#             [[['server'], [['listen', '69.50.225.155:9000'],
#                            ['listen', '127.0.0.1'],
#                            ['server_name', '.example.com'],
#                            ['server_name', 'example.*'],
#                            []]]])
# 

    def test_add_server_directives(self):
        nparser = better_parser.FancyNginxParser(self.config_path)
        mock_vhost = obj.VirtualHost(nparser.abs_path('nginx.conf'),
                                     None, None, None,
                                     set(['localhost',
                                           r'~^(www\.)?(example|bar)\.']),
                                     None, [10, 1, 9])
        nparser.add_server_directives(mock_vhost,
                                      [['foo', 'bar'], ['\n ', 'ssl_certificate', ' ',
                                                        '/etc/ssl/cert.pem']],
                                      replace=False)
        ssl_re = re.compile(r'\n\s+ssl_certificate /etc/ssl/cert.pem')
        dump = nginxparser.dumps(nparser.parsed[nparser.abs_path('nginx.conf')])
        self.assertEqual(1, len(re.findall(ssl_re, dump)))

        example_com = nparser.abs_path('sites-enabled/example.com')
        names = set(['.example.com', 'example.*'])
        mock_vhost.filep = example_com
        mock_vhost.names = names
        mock_vhost.path = [0]
        nparser.add_server_directives(mock_vhost,
                                      [['foo', 'bar'], ['ssl_certificate',
                                                        '/etc/ssl/cert2.pem']],
                                      replace=False)
        nparser.add_server_directives(mock_vhost, [['foo', 'bar']],
                                      replace=False)
        from certbot_nginx.parser import COMMENT
        self.assertEqual(nparser.parsed[example_com],
            [[['server'], [['listen', '69.50.225.155:9000'],
                           ['listen', '127.0.0.1'],
                           ['server_name', '.example.com'],
                           ['server_name', 'example.*'],
                           ['foo', 'bar'],
                           ['#', COMMENT],
                           ['ssl_certificate', '/etc/ssl/cert2.pem'],
                           ['#', COMMENT], [], []
                           ]]])

        server_conf = nparser.abs_path('server.conf')
        names = set(['alias', 'another.alias', 'somename'])
        mock_vhost.filep = server_conf
        mock_vhost.names = names
        mock_vhost.path = []
        self.assertRaises(errors.MisconfigurationError,
                          nparser.add_server_directives,
                          mock_vhost,
                          [['foo', 'bar'],
                           ['ssl_certificate', '/etc/ssl/cert2.pem']],
                          replace=False)

#     def test_comment_is_repeatable(self):
#         nparser = parser.NginxParser(self.config_path)
#         example_com = nparser.abs_path('sites-enabled/example.com')
#         mock_vhost = obj.VirtualHost(example_com,
#                                      None, None, None,
#                                      set(['.example.com', 'example.*']),
#                                      None, [0])
#         nparser.add_server_directives(mock_vhost,
#                                       [['\n  ', '#', ' ', 'what a nice comment']],
#                                       replace=False)
#         nparser.add_server_directives(mock_vhost,
#                                       [['\n  ', 'include', ' ',
#                                       nparser.abs_path('comment_in_file.conf')]],
#                                       replace=False)
#         from certbot_nginx.parser import COMMENT
#         self.assertEqual(nparser.parsed[example_com],
#             [[['server'], [['listen', '69.50.225.155:9000'],
#                            ['listen', '127.0.0.1'],
#                            ['server_name', '.example.com'],
#                            ['server_name', 'example.*'],
#                            ['#', ' ', 'what a nice comment'],
#                            [],
#                            ['include', nparser.abs_path('comment_in_file.conf')],
#                            ['#', COMMENT],
#                            []]]]
# )
# 
#     def test_replace_server_directives(self):
#         nparser = parser.NginxParser(self.config_path)
#         target = set(['.example.com', 'example.*'])
#         filep = nparser.abs_path('sites-enabled/example.com')
#         mock_vhost = obj.VirtualHost(filep, None, None, None, target, None, [0])
#         nparser.add_server_directives(
#             mock_vhost, [['server_name', 'foobar.com']], replace=True)
#         from certbot_nginx.parser import COMMENT
#         self.assertEqual(
#             nparser.parsed[filep],
#             [[['server'], [['listen', '69.50.225.155:9000'],
#                            ['listen', '127.0.0.1'],
#                            ['server_name', 'foobar.com'], ['#', COMMENT],
#                            ['server_name', 'example.*'], []
#                            ]]])
#         mock_vhost.names = set(['foobar.com', 'example.*'])
#         nparser.add_server_directives(
#             mock_vhost, [['ssl_certificate', 'cert.pem']], replace=True)
#         self.assertEqual(
#             nparser.parsed[filep],
#             [[['server'], [['listen', '69.50.225.155:9000'],
#                            ['listen', '127.0.0.1'],
#                            ['server_name', 'foobar.com'], ['#', COMMENT],
#                            ['server_name', 'example.*'], [],
#                            ['ssl_certificate', 'cert.pem'], ['#', COMMENT], [],
#                            ]]])
# 
#     def test_get_best_match(self):
#         target_name = 'www.eff.org'
#         names = [set(['www.eff.org', 'irrelevant.long.name.eff.org', '*.org']),
#                  set(['eff.org', 'ww2.eff.org', 'test.www.eff.org']),
#                  set(['*.eff.org', '.www.eff.org']),
#                  set(['.eff.org', '*.org']),
#                  set(['www.eff.', 'www.eff.*', '*.www.eff.org']),
#                  set(['example.com', r'~^(www\.)?(eff.+)', '*.eff.*']),
#                  set(['*', r'~^(www\.)?(eff.+)']),
#                  set(['www.*', r'~^(www\.)?(eff.+)', '.test.eff.org']),
#                  set(['*.org', r'*.eff.org', 'www.eff.*']),
#                  set(['*.www.eff.org', 'www.*']),
#                  set(['*.org']),
#                  set([]),
#                  set(['example.com'])]
#         winners = [('exact', 'www.eff.org'),
#                    (None, None),
#                    ('exact', '.www.eff.org'),
#                    ('wildcard_start', '.eff.org'),
#                    ('wildcard_end', 'www.eff.*'),
#                    ('regex', r'~^(www\.)?(eff.+)'),
#                    ('wildcard_start', '*'),
#                    ('wildcard_end', 'www.*'),
#                    ('wildcard_start', '*.eff.org'),
#                    ('wildcard_end', 'www.*'),
#                    ('wildcard_start', '*.org'),
#                    (None, None),
#                    (None, None)]
# 
#         for i, winner in enumerate(winners):
#             self.assertEqual(winner,
#                              parser.get_best_match(target_name, names[i]))
# 
#     def test_comment_directive(self):
#         # pylint: disable=protected-access
#         block = nginxparser.UnspacedList([
#             ["\n", "a", " ", "b", "\n"],
#             ["c", " ", "d"],
#             ["\n", "e", " ", "f"]])
#         from certbot_nginx.parser import comment_directive, COMMENT_BLOCK
#         comment_directive(block, 1)
#         comment_directive(block, 0)
#         self.assertEqual(block.spaced, [
#             ["\n", "a", " ", "b", "\n"],
#             COMMENT_BLOCK,
#             "\n",
#             ["c", " ", "d"],
#             COMMENT_BLOCK,
#             ["\n", "e", " ", "f"]])
# 
#     def test_comment_out_directive(self):
#         server_block = nginxparser.loads("""
#             server {
#                 listen 80;
#                 root /var/www/html;
#                 index star.html;
# 
#                 server_name *.functorkitten.xyz;
#                 ssl_session_timeout 1440m; ssl_protocols TLSv1 TLSv1.1 TLSv1.2;
# 
#                 ssl_prefer_server_ciphers on;
#             }""")
#         block = server_block[0][1]
#         from certbot_nginx.parser import _comment_out_directive
#         _comment_out_directive(block, 4, "blah1")
#         _comment_out_directive(block, 5, "blah2")
#         _comment_out_directive(block, 6, "blah3")
#         self.assertEqual(block.spaced, [
#             ['\n                ', 'listen', ' ', '80'],
#             ['\n                ', 'root', ' ', '/var/www/html'],
#             ['\n                ', 'index', ' ', 'star.html'],
#             ['\n\n                ', 'server_name', ' ', '*.functorkitten.xyz'],
#             ['\n                ', '#', ' ssl_session_timeout 1440m; # duplicated in blah1'],
#             [' ', '#', ' ssl_protocols TLSv1 TLSv1.1 TLSv1.2; # duplicated in blah2'],
#             ['\n\n                ', '#', ' ssl_prefer_server_ciphers on; # duplicated in blah3'],
#             '\n            '])
# 
#     def test_parse_server_raw_ssl(self):
#         server = parser._parse_server_raw([ #pylint: disable=protected-access
#             ['listen', '443']
#         ])
#         self.assertFalse(server['ssl'])
# 
#         server = parser._parse_server_raw([ #pylint: disable=protected-access
#             ['listen', '443', 'ssl']
#         ])
#         self.assertTrue(server['ssl'])
# 
#         server = parser._parse_server_raw([ #pylint: disable=protected-access
#             ['listen', '443'], ['ssl', 'off']
#         ])
#         self.assertFalse(server['ssl'])
# 
#         server = parser._parse_server_raw([ #pylint: disable=protected-access
#             ['listen', '443'], ['ssl', 'on']
#         ])
#         self.assertTrue(server['ssl'])
# 
#     def test_parse_server_raw_unix(self):
#         server = parser._parse_server_raw([ #pylint: disable=protected-access
#             ['listen', 'unix:/var/run/nginx.sock']
#         ])
#         self.assertEqual(len(server['addrs']), 0)
# 
#     def test_parse_server_global_ssl_applied(self):
#         nparser = parser.NginxParser(self.config_path)
#         server = nparser.parse_server([
#             ['listen', '443']
#         ])
#         self.assertTrue(server['ssl'])
# 
#     def test_duplicate_vhost(self):
#         nparser = parser.NginxParser(self.config_path)
# 
#         vhosts = nparser.get_vhosts()
#         default = [x for x in vhosts if 'default' in x.filep][0]
#         new_vhost = nparser.duplicate_vhost(default, delete_default=True)
#         nparser.filedump(ext='')
# 
#         # check properties of new vhost
#         self.assertFalse(next(iter(new_vhost.addrs)).default)
#         self.assertNotEqual(new_vhost.path, default.path)
# 
#         # check that things are written to file correctly
#         new_nparser = parser.NginxParser(self.config_path)
#         new_vhosts = new_nparser.get_vhosts()
#         new_defaults = [x for x in new_vhosts if 'default' in x.filep]
#         self.assertEqual(len(new_defaults), 2)
#         new_vhost_parsed = new_defaults[1]
#         self.assertFalse(next(iter(new_vhost_parsed.addrs)).default)
#         self.assertEqual(next(iter(default.names)), next(iter(new_vhost_parsed.names)))
#         self.assertEqual(len(default.raw), len(new_vhost_parsed.raw))
#         self.assertTrue(next(iter(default.addrs)).super_eq(next(iter(new_vhost_parsed.addrs))))

if __name__ == "__main__":
    unittest.main()  # pragma: no cover
