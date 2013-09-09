import os
import time
from hashlib import sha1
from base64 import b64encode, b64decode

from pulsar.utils.httpurl import parse_dict_header, hexmd5, hexsha1, urlparse
from pulsar.utils.pep import native_str

__all__ = ['Auth',
           'keyAuth',
           'HTTPBasicAuth',
           'HTTPDigestAuth']
        

class Auth(object):
    '''Base class for managing authentication.
    '''
    type = None
    def __call__(self, response):
        raise NotImplementedError

    def __str__(self):
        return self.__repr__()


class KeyAuth(Auth):
    
    def __init__(self, **params):
        self.params = params
        
    def __call__(self, response):
        response.current_request.data.update(self.params)


class HTTPBasicAuth(Auth):
    '''HTTP Basic Authentication handler.'''
    def __init__(self, username, password):
        self.username = username
        self.password = password
        
    @property
    def type(self):
        return 'basic'

    def __call__(self, response):
        response.current_request.headers['Authorization'] = self.header()

    def header(self):
        b64 = b64encode(('%s:%s' % (
            self.username, self.password)).encode('latin1'))
        return 'Basic %s' % native_str(b64.strip(), 'latin1')

    def __repr__(self):
        return 'Basic: %s' % self.username


class HTTPDigestAuth(Auth):
    '''HTTP Digest Authentication handler.'''
    def __init__(self, username, password=None, options=None):
        self.username = username
        self.password = password
        self.last_nonce = None
        self.options = options or {}
        self.algorithm = self.options.pop('algorithm', 'MD5')
    
    @property
    def type(self):
        return 'digest'
    
    def __call__(self, response):
        # If we have a saved nonce, skip the 401
        request = response.current_request
        if self.last_nonce:
            request.headers['Authorization'] =\
                self.encode(request.method, request.full_url)
        else:
            # add post request handler
            response.bind_event('post_request', self.handle_401)

    def __repr__(self):
        return 'Digest: %s' % self.username

    def encode(self, method, uri):
        '''Called by the client to encode Authentication header.'''
        if not self.username or not self.password:
            return
        o = self.options
        qop = o.get('qop')
        realm = o.get('realm')
        nonce = o['nonce']
        entdig = None
        p_parsed = urlparse(uri)
        path = p_parsed.path
        if p_parsed.query:
            path += '?' + p_parsed.query
        KD = lambda s, d: self.hex("%s:%s" % (s, d))
        ha1 = self.ha1(realm, self.password)
        ha2 = self.ha2(qop, method, path)
        if qop == 'auth':
            if nonce == self.last_nonce:
                self.nonce_count += 1
            else:
                self.nonce_count = 1
            ncvalue = '%08x' % self.nonce_count
            s = str(self.nonce_count).encode('utf-8')
            s += nonce.encode('utf-8')
            s += time.ctime().encode('utf-8')
            s += os.urandom(8)
            cnonce = sha1(s).hexdigest()[:16]
            noncebit = "%s:%s:%s:%s:%s" % (nonce, ncvalue, cnonce, qop, ha2)
            respdig = KD(ha1, noncebit)
        elif qop is None:
            respdig = KD(ha1, "%s:%s" % (nonce, ha2))
        else:
            # XXX handle auth-int.
            return
        base = 'username="%s", realm="%s", nonce="%s", uri="%s", ' \
               'response="%s"' % (self.username, realm, nonce, path, respdig)
        opaque = o.get('opaque')
        if opaque:
            base += ', opaque="%s"' % opaque
        if entdig:
            base += ', digest="%s"' % entdig
            base += ', algorithm="%s"' % self.algorithm
        if qop:
            base += ', qop=%s, nc=%s, cnonce="%s"' % (qop, ncvalue, cnonce)
        return 'Digest %s' % (base)
        
    def handle_401(self, response):
        """Takes the given response and tries digest-auth, if needed."""
        if response.status_code == 401:
            request = response.current_request
            response._num_handle_401 = getattr(response, '_handle_401', 0) + 1
            s_auth = response.headers.get('www-authenticate', '')
            if 'digest' in s_auth.lower() and response._num_handle_401 < 2:
                self.options = parse_dict_header(s_auth.replace('Digest ', ''))
                headers = [('authorization', self.encode(
                    request.method, request.full_url))]
                response.producer.request(request.method, request.full_url,
                    headers=headers, response=response)
        
    def hex(self, x):
        if self.algorithm == 'MD5':
            return hexmd5(x)
        elif self.algorithm == 'SHA1':
            return hexsha1(x)
        else:
            raise ValueError('Unknown algorithm %s' % self.algorithm)
        
    def ha1(self, realm, password):
        return self.hex('%s:%s:%s' % (self.username, realm, password))
    
    def ha2(self, qop, method, uri, body=None):
        if qop == "auth" or qop is None:
            return self.hex("%s:%s" % (method, uri))
        elif qop == "auth-int":
            return self.hex("%s:%s:%s" % (method, uri, self.hex(body)))
        raise ValueError