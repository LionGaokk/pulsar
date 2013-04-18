import socket

import pulsar
from pulsar import is_failure
from pulsar.utils.pep import to_bytes, to_string
from pulsar.apps.test import unittest, run_on_arbiter, dont_run_with_thread

from examples.echo.manage import server, Echo

    
class SafeCallback(pulsar.Deferred):
    
    def __call__(self):
        try:
            r = self._call()
        except Exception as e:
            r = e
        if pulsar.is_async(r):
            return r.add_callback(self)
        else:
            return self.callback(r)
        
    def _call(self):
        raise NotImplementedError()
    

class TestPulsarStreams(unittest.TestCase):
    concurrency = 'thread'
    server = None
    
    @classmethod
    def setUpClass(cls):
        s = server(name=cls.__name__.lower(), bind='127.0.0.1:0',
                   concurrency=cls.concurrency)
        cls.server = yield pulsar.send('arbiter', 'run', s)
        
    def client(self, **params):
        return Echo(self.server.address, **params)
        
    @classmethod
    def tearDownClass(cls):
        if cls.server:
            yield pulsar.send('arbiter', 'kill_actor', cls.server.name)
        
    @run_on_arbiter
    def testServer(self):
        app = yield pulsar.get_application(self.__class__.__name__.lower())
        self.assertTrue(app.address)
        self.assertTrue(app.cfg.address)
        self.assertNotEqual(app.address, app.cfg.address)
        
    def test_client_first_request(self):
        client = self.client(full_response=True)
        self.assertFalse(client.concurrent_connections)
        self.assertFalse(client.available_connections)
        response = client.request(b'Test First request')
        result = yield response.on_finished
        self.assertEqual(result, b'Test First request')
        self.assertTrue(response.current_request)
        self.assertFalse(response.connection)
        self.assertFalse(client.concurrent_connections)
        self.assertEqual(client.available_connections, 1)
        self.assertEqual(response.request_processed, 1)
        connection = client.get_connection(response.current_request)
        self.assertEqual(client.concurrent_connections, 1)
        self.assertFalse(client.available_connections)
        self.assertEqual(connection.session, 1)
        self.assertEqual(connection.processed, 1)
        
        
@dont_run_with_thread
class TestPulsarStreamsProcess(TestPulsarStreams):
    impl = 'process'        

    