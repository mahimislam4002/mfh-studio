# MFH Studio

Portfolio SaaS + Productivity OS modules (Flask).

## Local run

```bash
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

## Deploy (Render)

1. Connect this GitHub repo on [Render](https://render.com)
2. New → Web Service
3. Build: `pip install -r requirements.txt`
4. Start: `python app.py`
5. Add env: `FLASK_SECRET_KEY=your-long-random-secret`

## Version

See `VERSION` file.
