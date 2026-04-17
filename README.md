# Packing Django App

This project deploys the particle-size packing notebook as a Django web interface.

## Features
- Upload up to four PSD CSV files (or use local defaults `PSD_unfit1.csv` to `PSD_unfit4.csv`)
- Edit mass fractions, densities, and beta factors
- Compute mixed PSD, packing density, and true packing at multiple compaction levels
- Render charts and class-wise packing table in-browser

## Expected CSV format
Each PSD file must include columns:
- `Size`
- `Acc from small`

## Run locally
1. Create/activate your Python environment.
2. Install dependencies:
   `pip install -r requirements.txt`
3. Apply migrations:
   `python manage.py migrate`
4. Start server:
   `python manage.py runserver`
5. Open:
   `http://127.0.0.1:8000`

## GitHub readiness checklist
1. Ensure secrets are not committed:
   - Keep `.env` out of version control (already ignored by `.gitignore`).
   - Use `.env.example` as the template for required variables.
2. Ensure generated/local data is not committed:
   - `db.sqlite3`, `media/`, and `staticfiles/` are ignored for deployment.
3. Before pushing, run:
   - `python manage.py check`
   - `python manage.py check --deploy` (with production env vars)

## PythonAnywhere deployment notes
1. Upload code from GitHub or by direct file upload.
2. Create a Python 3.9+ virtual environment and install dependencies:
   - `pip install -r requirements.txt`
3. In the PythonAnywhere Web app WSGI file, set environment variables (at minimum):
   - `DJANGO_SECRET_KEY`
   - `DJANGO_DEBUG=False`
   - `DJANGO_ALLOWED_HOSTS=yourusername.pythonanywhere.com`
   - `DJANGO_CSRF_TRUSTED_ORIGINS=https://yourusername.pythonanywhere.com`
4. In PythonAnywhere Web settings:
   - Point source code to this project folder.
   - Set WSGI config to load `packing_site.settings`.
   - Configure static files mapping: URL `/static/` to folder `.../static/`.
5. Run once after deploy:
   - `python manage.py migrate`
   - `python manage.py collectstatic --noinput`
6. Reload the PythonAnywhere web app.

## Project layout
- `packing_site/` Django project settings and URL config
- `packing_app/` form, views, and scientific calculation service
- `templates/` HTML templates
- `static/css/` custom styling
