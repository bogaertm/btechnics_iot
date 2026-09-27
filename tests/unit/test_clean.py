"""Unit test voor het maskeren van geheimen in de status (status._clean).

python3 tests/unit/test_clean.py
"""
import re, sys
src = open("custom_components/btechnics_branding/status.py").read()
start = src.index("_KEYS = ("); end = src.index("def _logs(")
ns = {"re": re, "Any": object}
exec(src[start:end], ns)
clean = ns["_clean"]
fails = 0
def check(inp, must_not=(), must=()):
    global fails
    out = clean(inp)
    bad = [x for x in must_not if x in out] + [x for x in must if x not in out]
    print("OK  " if not bad else "FOUT", repr(inp), "->", repr(out))
    fails += bool(bad)

check("{'password': 'hunter2', 'api_key': 'abc123'}", must_not=["hunter2", "abc123"])
check('{"token": "eyJhbGciOi.eyJzdWIiOi.sig", "client_secret":"s3cr3t"}', must_not=["s3cr3t", "eyJhbGciOi"])
check("Secret key: xyz987", must_not=["xyz987"])
check("https://user:p@ss@host/path", must_not=["p@ss", "user:"], must=["host/path"])
check("GET /bot123456:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw/sendMessage", must_not=["AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"])
check("url?api_key%3Dabc123def&x=1", must_not=["abc123def"])
check("Authorization: Bearer abcdefghijklmnop1234", must_not=["abcdefghijklmnop1234"])
check("connect to 192.168.1.20 failed", must_not=["192.168.1.20"])
check("host fe80:0:0:0:1c2d:3e4f:5a6b:7c8d down", must_not=["1c2d:3e4f"])
check("key=Zx9Qm2Lp8Rt4Vw6Yb1Nc3Df5", must_not=["Zx9Qm2Lp8Rt4Vw6Yb1Nc3Df5"])
check("random AbCdEfGh12345678IjKlMnOp9 in tekst", must_not=["AbCdEfGh12345678IjKlMnOp9"])
# niet te gretig
check("Error code 500 from server", must=["code 500"])
check("Invalid auth for user test", must=["Invalid auth for user"])
check("Token expired, refreshing", must=["Token expired"])
check("sensor.living_room_temperature_humidity_sensor unavailable", must=["living_room_temperature_humidity_sensor"])
check("Update finished at 12:30:45", must=["12:30:45"])
check("<img src=x onerror=alert(1)>", must_not=["<img", ">"])
# tweede ronde (hercontrole)
check("wifi_password=abc123 mqtt_password=xyz", must_not=["abc123", "xyz"])
check("pass=Hunter2! psk=MyWifiPass123 pin=1234 code=5678", must_not=["Hunter2", "MyWifiPass123", "1234", "5678"])
check("password: 'has space in it'", must_not=["space in it"])
check('"password": "p,a;ss"', must_not=["a;ss", "p,a"])
check("POST /api/webhook/abcdEFGH1234ijkl HTTP", must_not=["abcdEFGH1234ijkl"])
check("token ghp_abcdefghijklmnopqrstuvwxyz0123456789", must_not=["ghp_abcdefghij"])
check("AKIAIOSFODNN7EXAMPLE used", must_not=["AKIAIOSFODNN7EXAMPLE"])
check("https://hooks.slack.com/services/T000/B000/XXXXXXXX", must_not=["T000/B000"])
check("Authorization: Bearer short123", must_not=["short123"])
check("mail naar john.doe@gmail.com", must_not=["john.doe@gmail.com"])
sys.exit(1 if fails else 0)
