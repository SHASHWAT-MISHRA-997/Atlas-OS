# Using ATLAS from your phone

ATLAS runs on your computer. Your phone talks to that computer. There are three ways to connect, from simplest to most capable.

| | Same Wi-Fi | Tailscale (recommended for outside home) | Your own certificate |
|---|---|---|---|
| Works away from home | No | Yes | Only if you open a port (not recommended) |
| Encrypted (HTTPS) | No | Yes | Yes |
| Install as an app with offline screen | Add to Home screen only | Yes | Yes, if the phone trusts the certificate |
| Pairing QR code | Yes, after setting the address | Yes | Yes |
| Verified in this project | Pairing flow tested in a browser, not on a real phone | **Not verified**: needs a real Tailscale account and devices | HTTPS start-up tested with a self-signed certificate (`tests/test_serve.py`) |

Every option still needs login: each phone is paired once from the Devices screen and can be removed there at any time. Do not turn off `ATLAS_AUTH_REQUIRED`.

## 1. Same Wi-Fi (plain HTTP)

1. Find the computer's Wi-Fi address. The Devices screen shows a hint when it can detect it, such as `192.168.1.5`.
2. Start ATLAS listening on the network:

   ```
   cd backend
   set ATLAS_HOST=0.0.0.0              (PowerShell: $env:ATLAS_HOST="0.0.0.0")
   set ATLAS_ALLOWED_HOSTS=192.168.1.5
   set ATLAS_PUBLIC_URL=http://192.168.1.5:8000
   python -m app.serve
   ```

3. On the computer, open `http://localhost:8000`, then go to **Devices** and choose **Create pairing link**. With `ATLAS_PUBLIC_URL` set, a QR code appears.
4. Scan it with the phone camera within 10 minutes. The code works only once.

Traffic is not encrypted, so anyone on the same Wi-Fi could read it. Use this only at home. Windows Firewall will ask whether to allow Python on private networks; allow **private** only.

## 2. Tailscale (HTTPS, works anywhere)

[Tailscale](https://tailscale.com) makes a private network between your own devices. ATLAS stays closed to the internet, and Tailscale gives it a real HTTPS certificate on a `*.ts.net` name.

1. Install Tailscale on the computer and the phone, and sign in to the same account on both.
2. In the Tailscale admin console, turn on **MagicDNS** and **HTTPS certificates**.
3. Start ATLAS normally. It stays on `127.0.0.1`, so the network cannot reach it directly:

   ```
   cd backend
   set ATLAS_ALLOWED_HOSTS=your-pc.your-tailnet.ts.net
   set ATLAS_PUBLIC_URL=https://your-pc.your-tailnet.ts.net
   python -m app.serve
   ```

4. In another terminal, run `tailscale serve --bg 8000`. Check the exact command with `tailscale serve --help`, because it has changed between Tailscale versions.
5. Pair the phone from **Devices** as above. Over HTTPS, the browser offers **Install app**, and the app shows its offline screen when the computer is off.

Do **not** use `tailscale funnel`. It publishes ATLAS to the whole internet.

**Why this is safe with ATLAS's login.** A browser on the computer itself is signed in as the owner automatically. Tailscale Serve also connects from `127.0.0.1`, so since v0.7 ATLAS gives the automatic owner login only when the request has a loopback Host name and **no** forwarding headers (`X-Forwarded-For`, `Tailscale-User-Login`, `Forwarded`, `CF-Connecting-IP` and others). Requests through the tunnel must be paired like any other device. This is tested in `tests/test_devices.py::test_a_proxy_on_this_computer_does_not_make_visitors_the_owner`.

## 3. Your own certificate

If you already have a certificate for a name your phone trusts:

```
set ATLAS_HOST=0.0.0.0
set ATLAS_TLS_CERT=C:\path\to\cert.pem
set ATLAS_TLS_KEY=C:\path\to\key.pem
set ATLAS_ALLOWED_HOSTS=atlas.example.com
set ATLAS_PUBLIC_URL=https://atlas.example.com:8000
python -m app.serve
```

A self-signed certificate works for testing, but phones show a warning, and the app cannot be installed until the phone trusts the certificate.

Opening a port on your router exposes ATLAS to the internet. ATLAS has login, rate limits and per-device revocation, but it has not had a professional security review. Prefer Tailscale.

## What the phone can and cannot do

- **It can** chat, use memories, create tasks, and approve PC actions. Each approval records which device approved it.
- **It cannot** manage paired devices. Only the computer running ATLAS can create pairing links or remove devices.
- **Lost phone:** on the computer, open Devices and choose **Remove**, or run `python -m app.auth revoke <id>`. To sign out every device, run `python -m app.auth revoke-all`.
