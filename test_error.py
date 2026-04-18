import requests
session = requests.Session()
res = session.post('http://127.0.0.1:5000/login', data={'username': 'admin', 'password': 'admin123'})
print("Login status:", res.status_code)
res = session.get('http://127.0.0.1:5000/my-claims')
print("My claims status:", res.status_code)
if res.status_code != 200:
    print(res.text[:1000])
res = session.get('http://127.0.0.1:5000/admin/claims')
print("Admin claims status:", res.status_code)
if res.status_code != 200:
    print(res.text[:1000])
