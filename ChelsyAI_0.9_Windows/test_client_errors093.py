"""Windows Client explains WHY the host is unreachable instead of one generic message."""
import socket
import ssl
import unittest
from urllib.error import URLError

from client_api import HostClient, HostError, explain_http_status, explain_network_error, validate_host

BASE = 'https://laptop.tail1234.ts.net'


class ClientErrorTests(unittest.TestCase):
    def test_causes_are_named(self):
        cases = {
            socket.gaierror(11001, 'getaddrinfo failed'): 'не найден',
            ConnectionRefusedError(10061, 'refused'): 'доступ для устройств на нём не включён',
            TimeoutError('timed out'): 'не отвечает',
            ssl.SSLCertVerificationError(1, 'CERTIFICATE_VERIFY_FAILED'): 'Сертификат',
        }
        for reason, expected in cases.items():
            self.assertIn(expected, explain_network_error(URLError(reason), BASE), type(reason).__name__)
        self.assertIn('Chelsy AI Host не запущен', explain_http_status(502))
        self.assertIsNone(explain_http_status(400))

    def test_ip_address_is_rejected_with_a_hint(self):
        with self.assertRaises(ValueError) as ctx:
            validate_host('https://100.101.102.103')
        self.assertIn('ts.net', str(ctx.exception))
        self.assertEqual(validate_host(BASE + '/'), BASE)

    def test_unreachable_host_raises_explained_host_error(self):
        client = HostClient('https://nonexistent-chelsy-host.invalid', lambda refresh=False: 'token', timeout=3)
        with self.assertRaises(HostError) as ctx:
            client.health()
        self.assertIsNone(ctx.exception.status)
        self.assertNotEqual(str(ctx.exception), '')


if __name__ == '__main__':
    unittest.main()
