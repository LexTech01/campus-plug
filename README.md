# Campus Plug

Peer-to-peer campus marketplace and freelance gig platform for university students in Ghana.

## Run Locally

**Prerequisites:** Python 3.10+

1. Create and activate a virtual environment (recommended):

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Copy environment variables and adjust as needed:

   ```bash
   cp .env.example .env
   ```

4. Start the Flask app:

   ```bash
   python app.py
   ```

5. Open [http://127.0.0.1:5000](http://127.0.0.1:5000)

## Demo Accounts

After the first run, the app seeds sample data. You can sign in with:

- `yaw@knust.edu.gh` / `Temp@12345678`
- `alexanderwinfred17@gmail.com` / `Admin@98765432` (admin)

## Environment Variables

See `.env.example` for available settings, including Paystack keys for MoMo escrow payments.
